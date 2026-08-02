"""
Tests for the event classifier.
"""

from src.intelligence.classification import EventType, Topic
from src.intelligence.classifier import EventClassifier
from src.models import GeoPoliticalEvent


def create_event(
    title: str,
    summary: str = "",
) -> GeoPoliticalEvent:
    return GeoPoliticalEvent(
        title=title,
        summary=summary,
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
    )


def test_detects_military_strike():

    event = create_event(
        "Missile strike hits military base"
    )

    EventClassifier().classify(event)

    assert event.event_type == EventType.MILITARY_STRIKE


def test_detects_country():

    event = create_event(
        "China announces new policy"
    )

    EventClassifier().classify(event)

    assert "China" in event.countries


def test_detects_actor():

    event = create_event(
        "Xi Jinping visits Moscow"
    )

    EventClassifier().classify(event)

    assert "Xi Jinping" in event.actors


def test_detects_politics_topic():

    event = create_event(
        "Prime minister resigns"
    )

    EventClassifier().classify(event)

    assert Topic.POLITICS in event.topics