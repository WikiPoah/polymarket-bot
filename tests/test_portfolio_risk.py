# File-Version: 1.1.0
"""Regression tests for portfolio-level paper-trading safeguards."""

from src.paper_trading.models import PaperDecision
from src.strategy.engine import StrategyDecision
from src.strategy.expected_value import StrategyAction
from src.strategy.portfolio_risk import (
    PortfolioRiskManager,
    RiskConfig,
)


def make_decision(**changes):
    values = dict(
        action=StrategyAction.BUY_YES,
        estimated_probability=.8,
        market_probability=.5,
        edge=.3,
        expected_value=.3,
        confidence=.8,
        position_size=.08,
        reasons=[],
        opportunity=None,
    )
    values.update(changes)
    return StrategyDecision(**values)


def open_record(size):
    return PaperDecision(
        id="open", timestamp="now", market={}, decision="BUY YES",
        market_probability=.5, estimated_probability=.7, edge=.2,
        confidence=.8, position_size=size, evidence_confidence=.8,
        evidence_count=1, supporting_sources=[], event_title="event",
        event_source="source", event_url="url",
    )


def test_valid_opportunity_is_accepted():
    result = PortfolioRiskManager().check(make_decision())
    assert result.accepted


def test_valid_buy_no_with_positive_stake_is_accepted():
    result = PortfolioRiskManager().check(make_decision(
        action=StrategyAction.BUY_NO,
        edge=-.3,
        expected_value=.3,
        position_size=.08,
    ))

    assert result.accepted


def test_confidence_and_edge_thresholds_reject():
    manager = PortfolioRiskManager()
    assert not manager.check(make_decision(confidence=.5)).accepted
    assert not manager.check(make_decision(edge=.01)).accepted


def test_high_position_and_risk_reward_are_rejected():
    manager = PortfolioRiskManager()
    assert not manager.check(make_decision(position_size=.2)).accepted
    assert not manager.check(make_decision(expected_value=.01)).accepted


def test_exposure_limit_and_portfolio_calculation():
    manager = PortfolioRiskManager(RiskConfig(max_portfolio_exposure=.20))
    check = manager.check(make_decision(position_size=.08), [open_record(.15)])
    assert not check.accepted
    assert check.state.exposure == .15
    assert check.state.available_capital == .85
    assert check.state.open_positions == 1


def test_rejection_becomes_ignore_with_reason():
    decision = PortfolioRiskManager().apply(make_decision(confidence=.2))
    assert decision.action == StrategyAction.IGNORE
    assert decision.position_size == 0.0
    assert "Risk rejected" in decision.reasons[-1]


def test_invalid_probability_is_rejected():
    assert not PortfolioRiskManager().check(
        make_decision(market_probability=1.5)
    ).accepted


def test_missing_probability_is_rejected_without_type_error():
    assert not PortfolioRiskManager().check(
        make_decision(market_probability=None)
    ).accepted
