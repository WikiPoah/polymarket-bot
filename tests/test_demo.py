# File-Version: 1.0.0
"""End-to-end tests for the deterministic offline portfolio demo."""

from src.dashboard.data import DashboardDataBuilder
from src.demo import run_demo
from src.monitoring import SystemStatusStore
from src.paper_trading.history import PaperTradingRecorder


def test_offline_demo_traverses_real_pipeline_and_is_repeatable(tmp_path, monkeypatch):
    def reject_network(*_args, **_kwargs):
        raise AssertionError("The offline demo attempted network access.")

    monkeypatch.setattr("socket.socket.connect", reject_network)
    output_dir = tmp_path / "demo_run"

    first = run_demo(output_dir=output_dir)
    first_history = first.history_path.read_bytes()
    first_status = first.status_path.read_bytes()
    second = run_demo(output_dir=output_dir)

    assert second.markets_loaded == 4
    assert second.geopolitical_candidates == 3
    assert len(second.supported_markets) == 2
    assert second.unsupported_markets == (
        "Will China not invade Taiwan before 2027?",
    )
    assert second.filtered_markets == (
        "Will Manchester United win its next match?",
    )
    assert second.evidence_records == 5
    assert second.relevant_evidence == 2
    assert [decision.action.value for decision in second.decisions] == [
        "BUY YES",
        "IGNORE",
    ]
    assert second.decisions[0].position_size > 0
    assert second.decisions[0].opportunity.match_reasons
    assert "Country: China (+25)" in second.decisions[0].opportunity.match_reasons
    assert any(
        "below the required 5.0%" in reason
        for reason in second.decisions[1].reasons
    )

    records = PaperTradingRecorder(second.history_path).load()
    assert [record.id for record in records] == [
        "demo-decision-001",
        "demo-decision-002",
    ]
    assert [record.risk_status for record in records] == ["ACCEPTED", "IGNORED"]
    assert records[0].supporting_sources == ["BBC", "UN News"]
    assert records[0].evidence_count == 2
    assert all("interest rate" not in record.event_title.lower() for record in records)

    status = SystemStatusStore(second.status_path).latest()
    assert status is not None
    assert status.success
    assert status.run_id == "offline-demo-run"
    assert status.markets_analyzed == 3
    assert status.decisions_generated == 2
    assert status.provider_status == {"FixtureIntelligenceProvider": "OK"}

    dashboard = DashboardDataBuilder(
        PaperTradingRecorder(second.history_path),
        SystemStatusStore(second.status_path),
    ).build()
    assert dashboard["decision_funnel"] == {
        "evaluated": 2,
        "accepted": 1,
        "risk_rejected": 0,
        "ignored": 1,
        "settled": 0,
    }
    assert dashboard["system"]["health"] == "HEALTHY"
    assert second.history_path.read_bytes() == first_history
    assert second.status_path.read_bytes() == first_status
