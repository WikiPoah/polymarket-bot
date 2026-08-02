"""
Tests for intelligence pipeline relevance filtering.
"""

from src.intelligence.classification import EventType
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.outcomes import Outcome
from src.intelligence.pipeline import IntelligencePipeline
from src.models import GeoPoliticalEvent


def create_event(
    title: str,
    *,
    countries: list[str] | None = None,
    actors: list[str] | None = None,
    event_type: EventType = EventType.OTHER,
    outcome: Outcome = Outcome.OTHER,
) -> GeoPoliticalEvent:
    return GeoPoliticalEvent(
        title=title,
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
        countries=countries or [],
        actors=actors or [],
        event_type=event_type,
        outcome=outcome,
    )


def xi_market():
    return MarketClassifier().classify(
        {"question": "Xi Jinping out before 2027?"}
    )


def invasion_market():
    return MarketClassifier().classify(
        {"question": "Will China invade Taiwan before 2027?"}
    )


def test_leadership_market_accepts_matching_actor():
    event = create_event(
        "Xi Jinping makes a statement",
        countries=["China"],
        actors=["Xi Jinping"],
        event_type=EventType.LEADERSHIP,
    )

    assert IntelligencePipeline(None)._is_relevant(event, xi_market())


def test_leadership_market_rejects_general_news_mentioning_actor():
    event = create_event(
        "Xi Jinping discusses economic growth",
        countries=["China"],
        actors=["Xi Jinping"],
        event_type=EventType.ECONOMIC,
        outcome=Outcome.ECONOMIC_POLICY,
    )

    assert not IntelligencePipeline(None)._is_relevant(event, xi_market())


def test_xi_leadership_market_accepts_ccp_actor():
    event = create_event(
        "CCP succession dispute",
        countries=["China"],
        actors=["CCP"],
        event_type=EventType.LEADERSHIP,
    )

    assert IntelligencePipeline(None)._is_relevant(
        event,
        xi_market(),
    )


def test_leadership_market_accepts_leadership_event_in_country():
    event = create_event(
        "Chinese leadership succession discussion",
        countries=["China"],
        event_type=EventType.LEADERSHIP,
    )

    assert IntelligencePipeline(None)._is_relevant(
        event,
        xi_market(),
    )


def test_leadership_market_rejects_country_event_with_broad_outcome():
    event = create_event(
        "China central bank injects liquidity",
        countries=["China"],
        outcome=Outcome.ECONOMIC_POLICY,
    )

    assert not IntelligencePipeline(None)._is_relevant(
        event,
        xi_market(),
    )


def test_leadership_market_rejects_china_flood_with_outcome():
    event = create_event(
        "China flood emergency",
        countries=["China"],
        outcome=Outcome.NATURAL_DISASTER,
    )

    assert not IntelligencePipeline(None)._is_relevant(
        event,
        xi_market(),
    )


def test_military_market_rejects_economic_country_overlap():
    event = create_event(
        "China reports slower economic growth",
        countries=["China"],
        event_type=EventType.ECONOMIC,
        outcome=Outcome.ECONOMIC_POLICY,
    )

    assert not IntelligencePipeline(None)._is_relevant(event, invasion_market())
