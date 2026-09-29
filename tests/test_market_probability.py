# File-Version: 1.0.0
"""Regression tests for fail-closed Polymarket probability extraction."""

from datetime import datetime
import json

import pytest

from src.models import GeoPoliticalEvent, ScoredEvent, TradingOpportunity
from src.strategy.engine import StrategyEngine
from src.strategy.expected_value import StrategyAction
from src.strategy.market_probability import MarketProbabilityExtractor


def opportunity(*, outcomes='["Yes", "No"]', prices='["0.40", "0.60"]'):
    event = GeoPoliticalEvent(
        title="Xi Jinping resigns",
        summary="",
        category="POLITICAL",
        subcategory="",
        country="China",
        region=None,
        continent=None,
        significance=.9,
        confidence=.9,
        market_sensitivity=.9,
        source_url="",
        published_at=datetime.now(),
        evidence_confidence=.9,
    )
    return TradingOpportunity(
        event=ScoredEvent(event=event, score=90),
        market={
            "question": "Will Xi Jinping be removed before 2027?",
            "outcomes": outcomes,
            "outcomePrices": prices,
        },
        match_score=90,
        confidence=.9,
    )


@pytest.mark.parametrize(
    ("outcomes", "prices"),
    [
        ("not-json", '["0.40", "0.60"]'),
        ('["Yes", "No"]', "not-json"),
        ('["Yes", "No"]', '["0.40"]'),
        ('["Up", "Down"]', '["0.40", "0.60"]'),
        ('["Yes", "No"]', '["unknown", "0.60"]'),
        ('["Yes", "No"]', '["NaN", "0.60"]'),
        ('["Yes", "No"]', '["Infinity", "0.60"]'),
        ('["Yes", "No"]', '["-0.01", "1.01"]'),
        ('["Yes", "No"]', '["1.01", "-0.01"]'),
        ('["Yes", "No"]', '["0", "1"]'),
        ('["Yes", "No"]', '["1", "0"]'),
    ],
)
def test_invalid_or_untradable_probability_returns_none(outcomes, prices):
    assert MarketProbabilityExtractor().extract(
        opportunity(outcomes=outcomes, prices=prices)
    ) is None


def test_valid_normal_yes_probability_is_extracted():
    assert MarketProbabilityExtractor().extract(opportunity()) == pytest.approx(.4)


@pytest.mark.parametrize(
    "prices",
    [
        "not-json",
        json.dumps(["0", "1"]),
    ],
)
def test_invalid_probability_cannot_produce_either_trade_action(prices):
    decision = StrategyEngine().evaluate(opportunity(prices=prices))

    assert decision.action == StrategyAction.IGNORE
    assert decision.action not in {StrategyAction.BUY_YES, StrategyAction.BUY_NO}
    assert decision.market_probability is None
    assert decision.edge == 0.0
    assert decision.position_size == 0.0
    assert decision.reasons == [
        "Ignored: invalid market probability; no valid tradable YES price was available."
    ]
