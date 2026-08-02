"""
Tests for market-aware event scoring.
"""

from src.intelligence.classification import EventType, Region
from src.intelligence.outcomes import Outcome
from src.intelligence.scorer import score_events
from src.models import ClassifiedMarket, GeoPoliticalEvent


def create_event(
    *,
    event_type: EventType,
    outcome: Outcome = Outcome.OTHER,
    actors: list[str] | None = None,
    countries: list[str] | None = None,
) -> GeoPoliticalEvent:
    return GeoPoliticalEvent(
        title="Event",
        summary="",
        category="POLITICAL",
        subcategory="",
        country=None,
        region=None,
        continent=None,
        significance=None,
        confidence=None,
        market_sensitivity=None,
        source_url="",
        published_at=None,
        event_type=event_type,
        outcome=outcome,
        actors=actors or [],
        countries=countries or [],
    )


def create_market() -> ClassifiedMarket:
    return ClassifiedMarket(
        market={"question": "Xi Jinping out before 2027?"},
        event_type=EventType.LEADERSHIP,
        expected_outcome=Outcome.LEADER_REMOVED,
        classified_region=Region.EAST_ASIA,
        actors=["Xi Jinping"],
        countries=["China"],
    )


def test_direct_leadership_removal_ranks_highest():
    direct_removal = create_event(
        event_type=EventType.LEADERSHIP,
        outcome=Outcome.LEADER_REMOVED,
        actors=["Xi Jinping"],
        countries=["China"],
    )
    ccp_crisis = create_event(
        event_type=EventType.LEADERSHIP,
        actors=["CCP"],
        countries=["China"],
    )
    succession = create_event(
        event_type=EventType.LEADERSHIP,
        countries=["China"],
    )

    scored_events = score_events(
        [succession, ccp_crisis, direct_removal],
        create_market(),
    )

    assert [scored.event for scored in scored_events] == [
        direct_removal,
        ccp_crisis,
        succession,
    ]


def test_generic_china_economic_event_scores_below_leadership_event():
    leadership_event = create_event(
        event_type=EventType.LEADERSHIP,
        countries=["China"],
    )
    economic_event = create_event(
        event_type=EventType.ECONOMIC,
        outcome=Outcome.ECONOMIC_POLICY,
        countries=["China"],
    )

    scored_events = score_events(
        [economic_event, leadership_event],
        create_market(),
    )

    assert scored_events[0].event is leadership_event
    assert scored_events[0].score > scored_events[1].score


def test_multiple_sources_increase_event_score():
    event = create_event(
        event_type=EventType.LEADERSHIP,
        actors=["Xi Jinping"],
        countries=["China"],
    )
    event.evidence_confidence = 0.50
    one_source_score = score_events(
        [event],
        create_market(),
    )[0].score

    event.evidence_confidence = 0.95
    multiple_source_score = score_events(
        [event],
        create_market(),
    )[0].score

    assert multiple_source_score > one_source_score
