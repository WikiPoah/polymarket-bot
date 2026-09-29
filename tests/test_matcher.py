# File-Version: 1.0.0
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
        supported_proposition=True,
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


def test_matches_ccp_leadership_crisis():

    event = create_event()
    event.title = "CCP leadership crisis"
    event.actors = ["CCP"]
    event.outcome = Outcome.OTHER

    opportunities = find_matching_markets(
        ScoredEvent(event=event, score=80),
        [create_market()],
    )

    assert len(opportunities) == 1
    assert "Actor: CCP (+20)" in opportunities[0].match_reasons


def test_matches_chinese_leadership_succession_without_actor():

    event = create_event()
    event.title = "Chinese leadership succession event"
    event.actors = []
    event.outcome = Outcome.OTHER

    opportunities = find_matching_markets(
        ScoredEvent(event=event, score=80),
        [create_market()],
    )

    assert len(opportunities) == 1


def test_rejects_xi_diplomatic_event():

    event = create_event()
    event.title = "Xi Jinping meets foreign leaders"
    event.event_type = EventType.DIPLOMATIC
    event.outcome = Outcome.OTHER

    opportunities = find_matching_markets(
        ScoredEvent(event=event, score=80),
        [create_market()],
    )

    assert opportunities == []


def test_rejects_china_economic_policy_event():

    event = create_event()
    event.title = "China announces economic policy"
    event.actors = []
    event.event_type = EventType.ECONOMIC
    event.outcome = Outcome.ECONOMIC_POLICY

    opportunities = find_matching_markets(
        ScoredEvent(event=event, score=80),
        [create_market()],
    )

    assert opportunities == []


def test_rejects_market_marked_as_unsupported():
    market = create_market()
    market.supported_proposition = False
    market.unsupported_reason = "Unsupported proposition: explicit negation."

    opportunities = find_matching_markets(
        ScoredEvent(event=create_event(), score=80),
        [market],
    )

    assert opportunities == []
