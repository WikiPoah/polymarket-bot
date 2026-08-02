"""
Tests for the market classifier.
"""

from src.intelligence.classification import EventType, Topic
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.outcomes import Outcome


def classify(question: str):
    market = {
        "question": question,
    }

    return MarketClassifier().classify(market)


def test_detects_leadership_market():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert market.event_type == EventType.LEADERSHIP


def test_detects_country():

    market = classify(
        "Will China invade Taiwan?"
    )

    assert "China" in market.countries


def test_detects_actor():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert "Xi Jinping" in market.actors


def test_detects_politics_topic():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert Topic.POLITICS in market.topics


def test_detects_expected_outcome():

    market = classify(
        "Will Xi Jinping be removed before 2027?"
    )

    assert market.expected_outcome == Outcome.LEADER_REMOVED