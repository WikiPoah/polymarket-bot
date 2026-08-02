"""Tests for chronological paper-decision backtesting."""

import json

import pytest

from src.paper_trading.backtesting import BacktestConfig, BacktestEngine
from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision


def decision(**overrides):
    values = dict(
        id="1", timestamp="2026-01-02T00:00:00+00:00", market={},
        decision="BUY YES", market_probability=.4, estimated_probability=.7,
        edge=.3, confidence=.85, position_size=.1, evidence_confidence=.9,
        evidence_count=2, supporting_sources=["BBC"], event_title="Event",
        event_source="BBC", event_url="url", event_type="LEADERSHIP",
        resolved_yes=True, result=None, profit_loss=0.0,
    )
    values.update(overrides)
    return PaperDecision(**values)


def test_loads_historical_records_and_replays_chronologically(tmp_path):
    recorder = PaperTradingRecorder(tmp_path / "history.json")
    recorder.save([
        decision(id="later"),
        decision(id="earlier", timestamp="2026-01-01T00:00:00+00:00"),
    ])

    report = BacktestEngine().run_from_recorder(recorder)

    assert [item.id for item in report.decisions] == ["earlier", "later"]


def test_replay_calculates_outcomes_summary_and_drawdown():
    report = BacktestEngine().run([
        decision(id="win"),
        decision(id="loss", timestamp="2026-01-03T00:00:00+00:00", resolved_yes=False),
    ])

    assert report.summary.executed_trades == 2
    assert report.summary.wins == 1
    assert report.summary.losses == 1
    assert report.summary.win_rate == .5
    assert report.summary.profit_loss == pytest.approx(.02)
    assert report.summary.average_edge == pytest.approx(.3)
    assert report.summary.average_confidence == pytest.approx(.85)
    assert report.maximum_drawdown == pytest.approx(.04)
    assert report.performance_by_event_type["LEADERSHIP"].executed_trades == 2


def test_scenario_comparison_filters_confidence_edge_and_event_type():
    history = [
        decision(id="high", confidence=.9, edge=.3, event_type="LEADERSHIP"),
        decision(id="low", confidence=.4, edge=.1, event_type="ECONOMIC"),
    ]
    reports = BacktestEngine().compare(history, {
        "high_confidence": BacktestConfig(minimum_confidence=.8),
        "high_edge": BacktestConfig(minimum_edge=.2),
        "economic": BacktestConfig(event_types=frozenset({"ECONOMIC"})),
    })

    assert reports["high_confidence"].summary.executed_trades == 1
    assert reports["high_edge"].summary.executed_trades == 1
    assert reports["economic"].decisions[0].id == "low"


def test_empty_dataset_returns_empty_report():
    report = BacktestEngine().run([])
    assert report.summary.executed_trades == 0
    assert report.summary.win_rate == 0.0
    assert report.summary.profit_loss == 0.0
    assert report.maximum_drawdown == 0.0
    assert report.performance_by_event_type == {}


def test_invalid_records_do_not_prevent_loading_or_replay(tmp_path):
    path = tmp_path / "history.json"
    valid = decision().to_dict()
    path.write_text(json.dumps([{"id": "incomplete"}, "invalid", valid]), encoding="utf-8")
    recorder = PaperTradingRecorder(path)
    loaded = recorder.load()
    loaded.append(decision(id="bad-time", timestamp="not-a-date"))

    report = BacktestEngine().run(loaded)

    assert len(loaded) == 2
    assert [item.id for item in report.decisions] == ["1"]
    assert report.invalid_records == 1
