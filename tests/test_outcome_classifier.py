"""
Tests for the outcome classifier.
"""

from src.intelligence.outcome_classifier import OutcomeClassifier
from src.intelligence.outcomes import Outcome
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


def test_detects_leader_removed():

    event = create_event(
        "Prime minister resigns after confidence vote"
    )

    OutcomeClassifier().classify(event)

    assert event.outcome == Outcome.LEADER_REMOVED


def test_detects_military_escalation():

    event = create_event(
        "Missile strike launched against military base"
    )

    OutcomeClassifier().classify(event)

    assert event.outcome == Outcome.MILITARY_ESCALATION


def test_detects_sanctions():

    event = create_event(
        "Government imposes new sanctions"
    )

    OutcomeClassifier().classify(event)

    assert event.outcome == Outcome.SANCTIONS


def test_detects_natural_disaster():

    event = create_event(
        "Flood forces thousands to evacuate"
    )

    OutcomeClassifier().classify(event)

    assert event.outcome == Outcome.NATURAL_DISASTER


def test_unknown_event_defaults_to_other():

    event = create_event(
        "Local festival opens this weekend"
    )

    OutcomeClassifier().classify(event)

    assert event.outcome == Outcome.OTHER