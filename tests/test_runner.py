"""Tests for automated evaluation and persistent system status."""

from datetime import datetime, timezone

from src.monitoring import SystemStatusStore
from threading import Event

from src.runner import EvaluationRunner, EvaluationScheduler


class MarketSource:
    def __init__(self, markets=None, error=None):
        self.markets = markets or []
        self.error = error

    def get_active_markets(self):
        if self.error:
            raise self.error
        return self.markets


class Pipeline:
    def __init__(
        self, decisions=None, provider_status=None, provider_errors=None,
        provider_details=None,
    ):
        self.decisions = decisions or []
        self.provider_status = provider_status or {}
        self.provider_errors = provider_errors or []
        self.provider_details = provider_details or {}
        self.received = None
        self.reset = False

    def reset_provider_status(self):
        self.reset = True

    def run(self, markets):
        self.received = markets
        return self.decisions


def fixed_clock():
    return datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def test_runner_executes_pipeline_and_persists_status(tmp_path):
    pipeline = Pipeline(decisions=[object(), object()], provider_status={"RSS": "OK"})
    store = SystemStatusStore(tmp_path / "status.json")
    runner = EvaluationRunner(
        MarketSource([{"id": "1"}, {"id": "2"}]), pipeline, store,
        market_filter=lambda markets: markets[:1], clock=fixed_clock,
        run_id_factory=iter(["run-1", "run-2"]).__next__,
    )

    result = runner.run_once()

    assert pipeline.reset
    assert pipeline.received == [{"id": "1"}]
    assert result.status.success
    assert result.status.markets_analyzed == 1
    assert result.status.decisions_generated == 2
    assert result.status.run_id == "run-1"
    assert store.latest() == result.status
    runner.run_once()
    persisted = SystemStatusStore(tmp_path / "status.json").load()
    assert [item.run_id for item in persisted] == ["run-1", "run-2"]


def test_runner_records_provider_failure_as_degraded_success(tmp_path):
    pipeline = Pipeline(
        provider_status={"GDELT": "ERROR", "RSS": "OK"},
        provider_errors=["GDELT: unavailable"],
    )
    result = EvaluationRunner(
        MarketSource([{"id": "1"}]), pipeline,
        SystemStatusStore(tmp_path / "status.json"), clock=fixed_clock,
    ).run_once()

    assert result.status.success
    assert result.status.provider_status["GDELT"] == "ERROR"
    assert result.status.errors == ["GDELT: unavailable"]


def test_runner_records_market_failure_and_continues_safely(tmp_path):
    store = SystemStatusStore(tmp_path / "status.json")
    result = EvaluationRunner(
        MarketSource(error=RuntimeError("market API unavailable")), Pipeline(),
        store, clock=fixed_clock,
    ).run_once()

    assert not result.status.success
    assert result.decisions == ()
    assert "market API unavailable" in result.status.errors[0]
    assert store.latest() == result.status


def test_status_store_empty_state(tmp_path):
    store = SystemStatusStore(tmp_path / "missing.json")
    assert store.load() == []
    assert store.latest() is None
    assert store.last_successful() is None


def test_scheduler_stops_gracefully_after_callback():
    stop = Event()
    calls = []

    class Runner:
        def run_once(self):
            calls.append("run")
            return object()

    EvaluationScheduler(.01).run(
        Runner(), stop_event=stop, on_result=lambda _result: stop.set(),
    )

    assert calls == ["run"]
