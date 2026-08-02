"""
Tests for the strategy engine.
"""

from datetime import datetime

from src.intelligence.classification import (
    EventType,
    Region,
)
from src.intelligence.outcomes import Outcome
from src.models import (
    ClassifiedMarket,
    GeoPoliticalEvent,
    ScoredEvent,
)
from src.intelligence.matcher import find_matching_markets
from src.strategy.expected_value import (
    ExpectedValueCalculator,
    StrategyAction,
)
from src.strategy.position_sizing import PositionSizer
from src.strategy.probability import ProbabilityEstimator


def create_event() -> GeoPoliticalEvent:
    return GeoPoliticalEvent(
        title="Xi Jinping resigns",
        summary="",
        category="POLITICAL",
        subcategory="",
        country="China",
        region=None,
        continent=None,
        significance=0.9,
        confidence=0.9,
        market_sensitivity=0.9,
        source_url="",
        published_at=datetime.now(),
        event_type=EventType.LEADERSHIP,
        outcome=Outcome.LEADER_REMOVED,
        classified_region=Region.EAST_ASIA,
        countries=["China"],
        actors=["Xi Jinping"],
    )


def create_market() -> ClassifiedMarket:
    return ClassifiedMarket(
        market={
            "question": "Will Xi Jinping be removed before 2027?",
            "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.40","0.60"]',
        },
        event_type=EventType.LEADERSHIP,
        expected_outcome=Outcome.LEADER_REMOVED,
        classified_region=Region.EAST_ASIA,
        countries=["China"],
        actors=["Xi Jinping"],
    )


def create_opportunity():

    event = ScoredEvent(
        event=create_event(),
        score=90,
    )

    return find_matching_markets(
        event,
        [create_market()],
    )[0]


def test_probability_estimator():

    estimator = ProbabilityEstimator()

    probability = estimator.estimate(
        create_opportunity()
    )

    assert 0.0 <= probability <= 1.0


def test_expected_value_buy_yes():

    calculator = ExpectedValueCalculator()

    _, _, action = calculator.calculate(
        0.70,
        0.40,
    )

    assert action == StrategyAction.BUY_YES


def test_expected_value_buy_no():

    calculator = ExpectedValueCalculator()

    _, _, action = calculator.calculate(
        0.30,
        0.60,
    )

    assert action == StrategyAction.BUY_NO


def test_expected_value_ignore():

    calculator = ExpectedValueCalculator()

    _, _, action = calculator.calculate(
        0.50,
        0.50,
    )

    assert action == StrategyAction.IGNORE


def test_position_sizer():

    sizer = PositionSizer()

    position = sizer.calculate(
        edge=0.20,
        confidence=0.80,
    )

    assert 0.0 <= position <= 0.10