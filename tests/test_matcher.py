"""
Tests for the market matcher.
"""

from datetime import datetime

from src.intelligence.classification import (
    EventType,
    Region,
)
from src.intelligence.matcher import find_matching_markets
from src.intelligence.outcomes import Outcome
from src.models import (
    ClassifiedMarket,
    GeoPoliticalEvent,
    ScoredEvent,
)


def create_event() -> GeoPoliticalEvent:
    return GeoPoliticalEvent(
        title="Xi Jinping resigns",
        summary="",
        category="POLITICAL",
        subcategory="",
        country="China",
        region=None,
        continent=None,
        significance=None,
        confidence=None,
        market_sensitivity=None,
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
        },
        event_type=EventType.LEADERSHIP,
        expected_outcome=Outcome.LEADER_REMOVED,
        classified_region=Region.EAST_ASIA,
        countries=["China"],
        actors=["Xi Jinping"],
    )


def test_matching_market_found():

    event = ScoredEvent(
        event=create_event(),
        score=80,
    )

    opportunities = find_matching_markets(
        event,
        [create_market()],
    )

    assert len(opportunities) == 1


def test_match_score_positive():

    event = ScoredEvent(
        event=create_event(),
        score=80,
    )

    opportunity = find_matching_markets(
        event,
        [create_market()],
    )[0]

    assert opportunity.match_score > 0


def test_confidence_calculated():

    event = ScoredEvent(
        event=create_event(),
        score=80,
    )

    opportunity = find_matching_markets(
        event,
        [create_market()],
    )[0]

    assert opportunity.confidence > 0


def test_match_contains_reasons():

    event = ScoredEvent(
        event=create_event(),
        score=80,
    )

    opportunity = find_matching_markets(
        event,
        [create_market()],
    )[0]

    assert len(opportunity.match_reasons) > 0