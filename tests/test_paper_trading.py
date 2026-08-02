"""Tests for paper-trading persistence and performance."""

from datetime import datetime

import pytest

from src.intelligence.classification import EventType
from src.models import GeoPoliticalEvent, ScoredEvent, TradingOpportunity
from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision
from src.paper_trading.performance import PerformanceTracker
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


def test_empty_history_is_safe(tmp_path):
    assert PaperTradingRecorder(tmp_path / "missing.json").load() == []
    metrics = PerformanceTracker().calculate([])
    assert metrics.number_decisions == 0
    assert metrics.win_rate == 0.0
    assert metrics.profit_loss == 0.0


def test_settlement_and_performance_metrics(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    yes = recorder.record(make_decision())
    no = recorder.record(make_decision(StrategyAction.BUY_NO, .6))
    recorder.settle(yes.id, True)
    recorder.settle(no.id, False)
    metrics = PerformanceTracker().calculate(recorder.load())
    assert metrics.number_decisions == 2
    assert metrics.winning_decisions == 2
    assert metrics.losing_decisions == 0
    assert metrics.win_rate == 1.0
    assert metrics.profit_loss == pytest.approx(.1 * (.6 + .6))


def test_losing_settlement_has_negative_profit(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decision = recorder.record(make_decision())
    settled = recorder.settle(decision.id, False)
    assert settled.result == "LOSS"
    assert settled.profit_loss == pytest.approx(-.04)


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
