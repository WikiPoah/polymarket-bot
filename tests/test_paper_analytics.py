"""Tests for paper-trading analytics and calibration."""

from src.paper_trading.analytics import PerformanceAnalytics, format_report
from src.paper_trading.models import PaperDecision
import pytest


def decision(**overrides):
    values = dict(
        id="1", timestamp="2026-01-01T00:00:00+00:00", market={},
        decision="BUY YES", market_probability=.4, estimated_probability=.7,
        edge=.3, confidence=.85, position_size=.1, evidence_confidence=.9,
        evidence_count=3, supporting_sources=["BBC", "GDELT"],
        event_title="Leadership change", event_source="BBC", event_url="url",
        event_type="LEADERSHIP", result="WIN", resolved_yes=True, profit_loss=.06,
    )
    values.update(overrides)
    return PaperDecision(**values)


def test_analytics_calculations_and_breakdowns():
    report = PerformanceAnalytics().analyze([
        decision(),
        decision(id="2", event_type="ECONOMIC", confidence=.5,
                 evidence_count=1, result="LOSS", profit_loss=-.04),
        decision(id="3", decision="IGNORE", result=None, profit_loss=0.0),
    ])
    assert report.summary.total_decisions == 3
    assert report.summary.executed_trades == 2
    assert report.summary.wins == 1
    assert report.summary.losses == 1
    assert report.summary.average_edge == .3
    assert set(report.by_event_type) == {"LEADERSHIP", "ECONOMIC"}
    assert "HIGH" in report.by_confidence
    assert "SINGLE_SOURCE" in report.by_evidence_strength
    assert "+" in format_report(report)


def test_calibration_compares_predicted_and_actual():
    report = PerformanceAnalytics().analyze([
        decision(),
        decision(id="2", estimated_probability=.3, result="LOSS", profit_loss=-.03),
    ])
    assert len(report.calibration) == 2
    assert report.brier_score == pytest.approx(.09)


def test_empty_analytics_are_safe():
    report = PerformanceAnalytics().analyze([])
    assert report.summary.total_decisions == 0
    assert report.summary.executed_trades == 0
    assert report.summary.win_rate == 0.0
    assert report.calibration == []
    assert report.brier_score is None
