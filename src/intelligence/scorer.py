"""
Utilities for scoring geopolitical events.
"""

from src.intelligence.classification import EventType, Topic
from src.models import GeoPoliticalEvent, ScoredEvent


EVENT_TYPE_WEIGHTS = {
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
) -> list[ScoredEvent]:
    """
    Score and sort geopolitical events.
    """

    scored = [
        ScoredEvent(
            event=event,
            score=score_event(event),
        )
        for event in events
    ]

    scored.sort(
        key=lambda event: event.score,
        reverse=True,
    )

    return scored