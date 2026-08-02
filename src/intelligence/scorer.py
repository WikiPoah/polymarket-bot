"""
Utilities for scoring geopolitical events.
"""

from src.intelligence.classification import EventType, Topic
from src.intelligence.outcomes import Outcome
from src.models import (
    ClassifiedMarket,
    GeoPoliticalEvent,
    ScoredEvent,
)


EVENT_TYPE_WEIGHTS = {
    EventType.LEADERSHIP: 25,
    EventType.MILITARY_STRIKE: 35,
    EventType.INVASION: 35,
    EventType.MILITARY_EXERCISE: 25,
    EventType.NUCLEAR: 30,
    EventType.SANCTIONS: 25,
    EventType.ENERGY: 20,
    EventType.DIPLOMATIC: 15,
    EventType.ELECTION: 10,
    EventType.ECONOMIC: 10,
    EventType.SHIPPING: 20,
    EventType.TERRORISM: 30,
}


TOPIC_WEIGHTS = {
    Topic.MILITARY: 15,
    Topic.NUCLEAR: 15,
    Topic.ENERGY: 10,
    Topic.SHIPPING: 10,
    Topic.DIPLOMACY: 5,
    Topic.POLITICS: 5,
    Topic.ECONOMY: 5,
}


def score_market_event(
    event: GeoPoliticalEvent,
    market: ClassifiedMarket,
) -> int:
    """
    Score an event by evidence aligned with one market.
    """

    score = 0

    if (
        event.event_type != EventType.OTHER
        and event.event_type == market.event_type
    ):
        score += 30

    if (
        event.outcome != Outcome.OTHER
        and event.outcome == market.expected_outcome
    ):
        score += 30

    actor_match = any(
        actor in market.actors
        for actor in event.actors
    )

    ccp_match = (
        market.event_type == EventType.LEADERSHIP
        and "Xi Jinping" in market.actors
        and "China" in market.countries
        and "CCP" in event.actors
    )

    if actor_match or ccp_match:
        score += 20

    if any(
        country in market.countries
        for country in event.countries
    ):
        score += 10

    if event.significance is not None:
        score += int(event.significance * 20)

    if event.confidence is not None:
        score += int(event.confidence * 10)

    return min(score, 100)


def score_event(event: GeoPoliticalEvent) -> int:
    """
    Calculate the relevance score for a geopolitical event.
    """

    score = 0

    score += EVENT_TYPE_WEIGHTS.get(event.event_type, 0)

    for topic in event.topics:
        score += TOPIC_WEIGHTS.get(topic, 0)

    score += len(event.actors) * 5
    score += len(event.countries) * 5

    if event.significance is not None:
        score += int(event.significance * 20)

    if event.confidence is not None:
        score += int(event.confidence * 10)

    return min(score, 100)


def score_events(
    events: list[GeoPoliticalEvent],
    market: ClassifiedMarket | None = None,
) -> list[ScoredEvent]:
    """
    Score and sort geopolitical events.
    """

    scored = [
        ScoredEvent(
            event=event,
            score=(
                score_market_event(event, market)
                if market is not None
                else score_event(event)
            ),
        )
        for event in events
    ]

    scored.sort(
        key=lambda event: event.score,
        reverse=True,
    )

    return scored
