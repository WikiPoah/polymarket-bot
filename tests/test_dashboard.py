"""Tests for dashboard presentation data."""

import json
import threading
from urllib.request import urlopen

from src.dashboard.data import DashboardDataBuilder
from src.dashboard.demo import create_demo_history
from src.dashboard.server import create_server
from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision
from src.monitoring import RunStatus, SystemStatusStore


def make_record(**changes):
    values = dict(
        id="1", timestamp="2026-01-01T00:00:00+00:00",
        market={"question": "Xi Jinping out before 2027?"}, decision="BUY YES",
        market_probability=.4, estimated_probability=.7, edge=.3,
        confidence=.8, position_size=.08, evidence_confidence=.9,
        evidence_count=2, supporting_sources=["BBC", "GDELT"],
        event_title="Leadership change", event_source="BBC", event_url="url",
        event_type="LEADERSHIP", risk_status="ACCEPTED", risk_reason="",
        result="WIN", profit_loss=.048,
    )
    values.update(changes)
    return PaperDecision(**values)


def test_dashboard_data_generation(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    recorder.save([make_record(), make_record(id="2", result=None, profit_loss=0.0)])
    data = DashboardDataBuilder(recorder).build()
    assert data["current_opportunities"][0]["market_question"] == "Xi Jinping out before 2027?"
    assert data["performance"]["executed_trades"] == 2
    assert data["performance"]["win_rate"] == 1.0
    assert data["current_opportunities"][0]["risk_status"] == "ACCEPTED"


def test_dashboard_empty_state(tmp_path):
    data = DashboardDataBuilder(
        PaperTradingRecorder(tmp_path / "missing.json"),
        SystemStatusStore(tmp_path / "missing-status.json"),
    ).build()
    assert data["current_opportunities"] == []
    assert data["history"] == []
    assert data["performance"]["total_decisions"] == 0
    assert data["breakdowns"] == {"event_type": {}, "confidence": {}, "evidence_strength": {}}
    assert data["system"]["health"] == "UNKNOWN"
    assert data["system"]["latest_run"] is None
    assert data["recent_activity"] == []


def test_dashboard_reports_system_status_and_freshness(tmp_path):
    store = SystemStatusStore(tmp_path / "status.json")
    store.record(RunStatus(
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:01:00+00:00",
        success=True,
        markets_analyzed=4,
        decisions_generated=2,
        provider_status={"RSSProvider": "ERROR"},
        provider_details={
            "RSSProvider": {
                "status": "ERROR",
                "last_successful_run": "2025-12-31T23:00:00+00:00",
                "last_data_received": "2025-12-31T22:00:00+00:00",
                "event_age_seconds": 7260.0,
                "error": "unavailable",
            },
        },
        errors=["RSSProvider: unavailable"],
    ))

    data = DashboardDataBuilder(
        PaperTradingRecorder(tmp_path / "missing.json"), store,
    ).build()

    assert data["system"]["health"] == "DEGRADED"
    assert data["system"]["latest_run"]["markets_analyzed"] == 4
    assert data["system"]["last_successful_run"] == "2026-01-01T00:01:00+00:00"
    assert data["system"]["data_freshness"] == "2026-01-01T00:01:00+00:00"
    assert data["system"]["provider_freshness"]["RSSProvider"]["status"] == "ERROR"


def test_demo_history_is_locally_available(tmp_path):
    path = create_demo_history(tmp_path / "demo.json")
    data = DashboardDataBuilder(PaperTradingRecorder(path)).build()
    assert len(data["history"]) == 3
    assert data["performance"]["executed_trades"] == 3
    assert data["performance"]["wins"] == 1


def test_dashboard_server_loads_demo_history(tmp_path):
    path = create_demo_history(tmp_path / "demo.json")
    builder = DashboardDataBuilder(PaperTradingRecorder(path))
    server = create_server(builder, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        with urlopen(f"http://{host}:{port}/api/dashboard") as response:
            payload = json.load(response)
        assert payload["performance"]["total_decisions"] == 3
        assert payload["history"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
