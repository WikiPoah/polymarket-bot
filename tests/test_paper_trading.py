# File-Version: 1.3.1
"""Tests for paper-trading persistence and performance."""

from datetime import datetime, timedelta
import json

import pytest

from src.intelligence.classification import EventType
from src.models import GeoPoliticalEvent, ScoredEvent, TradingOpportunity
from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.performance import PerformanceTracker
from src.persistence import PersistenceCorruptionError
from src.strategy.engine import StrategyDecision
from src.strategy.expected_value import StrategyAction


def make_decision(action=StrategyAction.BUY_YES, market_probability=0.4):
    event = GeoPoliticalEvent(
        title="Xi Jinping resigns", summary="", category="POLITICAL", subcategory="",
        country="China", region=None, continent=None, significance=.9, confidence=.9,
        market_sensitivity=.9, source_url="https://example.test/event",
        published_at=datetime.now(), source="BBC", evidence_confidence=.9,
        event_type=EventType.LEADERSHIP, actors=["Xi Jinping"], countries=["China"],
    )
    opportunity = TradingOpportunity(
        event=ScoredEvent(event, 90), market={"question": "Xi out?"},
        match_score=90, confidence=.8,
    )
    return StrategyDecision(
        opportunity=opportunity, action=action, estimated_probability=.7,
        market_probability=market_probability, edge=.3, expected_value=.3,
        confidence=.8, position_size=.1, reasons=[],
    )


def test_record_and_load_decision(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    recorded = recorder.record(make_decision())
    loaded = recorder.load()
    assert len(loaded) == 1
    assert loaded[0].id == recorded.id
    assert loaded[0].evidence_count == 1


def test_record_persists_strategy_rationale(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = make_decision()
    decision.reasons = [
        "Bot estimate 70.0% versus market 40.0%.",
        "Accepted: BUY YES passed the strategy thresholds.",
    ]

    recorded = recorder.record(decision)

    assert recorded.rationale == "Accepted: BUY YES passed the strategy thresholds."
    assert recorder.load()[0].rationale == recorded.rationale
    assert recorder.load()[0].record_version == 3


def test_empty_history_is_safe(tmp_path):
    assert PaperTradingRecorder(tmp_path / "missing.json").load() == []
    metrics = PerformanceTracker().calculate([])
    assert metrics.number_decisions == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_loss == 0.0


def test_malformed_history_raises_and_record_preserves_original_bytes(tmp_path):
    path = tmp_path / "history.json"
    original = b'{"records": [broken'
    path.write_bytes(original)
    recorder = PaperTradingRecorder(path)

    with pytest.raises(PersistenceCorruptionError, match="history file is.*malformed"):
        recorder.load()
    with pytest.raises(PersistenceCorruptionError, match="refusing to overwrite"):
        recorder.record(make_decision())

    assert path.read_bytes() == original


def test_structurally_invalid_history_is_not_treated_as_empty(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"version": 3, "records": {}}), encoding="utf-8")

    with pytest.raises(PersistenceCorruptionError, match="records must be a list"):
        PaperTradingRecorder(path).load()


def test_successful_history_write_remains_atomic(tmp_path):
    path = tmp_path / "history.json"
    recorder = PaperTradingRecorder(path)

    recorder.record(make_decision())

    assert len(recorder.load()) == 1
    assert not path.with_suffix(".json.tmp").exists()


def test_winning_buy_yes_settlement_uses_stake_accounting(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision(StrategyAction.BUY_YES, .4))

    settled = recorder.settle(decision.id, True)

    assert settled.result == "WIN"
    assert settled.profit_loss == pytest.approx(.15)


def test_losing_buy_yes_settlement_loses_full_stake(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision(StrategyAction.BUY_YES, .4))

    settled = recorder.settle(decision.id, False)

    assert settled.result == "LOSS"
    assert settled.profit_loss == pytest.approx(-.1)


def test_winning_buy_no_settlement_uses_stake_accounting(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision(StrategyAction.BUY_NO, .6))

    settled = recorder.settle(decision.id, False)

    assert settled.result == "WIN"
    assert settled.profit_loss == pytest.approx(.15)


def test_losing_buy_no_settlement_loses_full_stake(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision(StrategyAction.BUY_NO, .6))

    settled = recorder.settle(decision.id, True)

    assert settled.result == "LOSS"
    assert settled.profit_loss == pytest.approx(-.1)


@pytest.mark.parametrize(
    ("action", "market_probability"),
    [
        (StrategyAction.BUY_YES, 0.0),
        (StrategyAction.BUY_NO, 1.0),
    ],
)
def test_zero_price_selected_side_is_invalid_without_profit(
    tmp_path,
    action,
    market_probability,
):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision(action, market_probability))

    settled = recorder.settle(decision.id, action == StrategyAction.BUY_YES)

    assert settled.result == "INVALID"
    assert settled.profit_loss == 0.0


@pytest.mark.parametrize("market_probability", [None, "0.4", float("nan")])
def test_non_numeric_or_non_finite_settlement_price_fails_closed(
    tmp_path,
    market_probability,
):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision(StrategyAction.BUY_YES, market_probability))

    settled = recorder.settle(decision.id, True)

    assert settled.result == "INVALID"
    assert settled.profit_loss == 0.0


def test_ignored_decision_is_not_a_loss(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision(StrategyAction.IGNORE))
    settled = recorder.settle(decision.id, False)
    metrics = PerformanceTracker().calculate(recorder.load())
    assert settled.result == "IGNORED"
    assert metrics.number_decisions == 1
    assert metrics.winning_decisions == 0
    assert metrics.losing_decisions == 0
    assert metrics.profit_loss == 0.0


def test_duplicate_opportunities_are_skipped_within_window(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    recorder.begin_run("run-1", timedelta(hours=1))
    first = recorder.record(make_decision())
    recorder.begin_run("run-2", timedelta(hours=1))
    duplicate = recorder.record(make_decision())

    assert first is not None
    assert first.run_id == "run-1"
    assert first.opportunity_id
    assert duplicate is None
    assert len(recorder.load()) == 1


def test_zero_duplicate_window_records_repeated_opportunity(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    recorder.begin_run("run-1", timedelta(0))
    recorder.record(make_decision())
    recorder.begin_run("run-2", timedelta(0))
    recorder.record(make_decision())
    assert len(recorder.load()) == 2


def test_legacy_history_migrates_to_versioned_envelope(tmp_path):
    path = tmp_path / "history.json"
    original = PaperTradingRecorder(path).record(make_decision())
    legacy_record = original.to_dict()
    legacy_record.pop("record_version")
    legacy_record.pop("run_id")
    legacy_record.pop("opportunity_id")
    path.write_text(json.dumps([legacy_record]), encoding="utf-8")

    recorder = PaperTradingRecorder(path)
    loaded = recorder.load()
    recorder.save(loaded)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert loaded[0].record_version == 1
    assert loaded[0].opportunity_id
    assert payload["version"] == 3
    assert len(payload["records"]) == 1
