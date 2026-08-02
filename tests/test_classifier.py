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


def test_extracts_location_date_and_significance():
    event = create_event(
        "Missile strike near Kyiv on August 2, 2026"
    )

    EventClassifier().classify(event)

    assert event.event_type == EventType.MILITARY_STRIKE
    assert "Kyiv" in event.locations
    assert "Ukraine" in event.countries
    assert "august 2, 2026" in event.mentioned_dates
    assert event.significance == .85


def test_economic_strike_is_not_misclassified_as_military():
    event = create_event("Workers strike over inflation and wages")

    EventClassifier().classify(event)

    assert event.event_type == EventType.ECONOMIC


def test_preserves_structured_provider_country_metadata():
    event = create_event("Government announces emergency measures")
    event.country = "Ukraine"

    EventClassifier().classify(event)

    assert event.countries == ["Ukraine"]
    assert event.locations == ["Ukraine"]
