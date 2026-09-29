# File-Version: 1.2.0
"""
Tests for intelligence pipeline relevance filtering.
"""

import logging
from datetime import datetime, timezone

from src.intelligence.classification import EventType
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.outcomes import Outcome
from src.intelligence.pipeline import IntelligencePipeline
from src.models import GeoPoliticalEvent
from src.paper_trading.history import PaperTradingRecorder
from src.strategy.expected_value import StrategyAction


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


def test_pipeline_uses_debug_logging_without_writing_stdout(caplog, capsys):
    class Client:
        provider_status = {}
        provider_errors = []
        provider_details = {}

        def fetch(self, query=None, limit=100):
            return []

        def reset_status(self):
            return None

    with caplog.at_level(logging.DEBUG, logger="src.intelligence.pipeline"):
        decisions = IntelligencePipeline(Client()).run([
            {"question": "Will China invade Taiwan before 2027?"},
        ])

    assert decisions == []
    assert "Intelligence query:" in caplog.text
    assert "Retrieved 0 events" in caplog.text
    assert capsys.readouterr().out == ""


def test_pipeline_skips_unsupported_negated_market_before_retrieval(caplog):
    class Client:
        provider_status = {}
        provider_errors = []
        provider_details = {}

        def __init__(self):
            self.fetches = 0

        def fetch(self, query=None, limit=100):
            self.fetches += 1
            return []

        def reset_status(self):
            return None

    client = Client()
    with caplog.at_level(logging.INFO, logger="src.intelligence.pipeline"):
        decisions = IntelligencePipeline(client).run([
            {"question": "Will China not invade Taiwan?"},
        ])

    assert decisions == []
    assert client.fetches == 0
    assert "explicit negation" in caplog.text


def test_supported_affirmative_market_reaches_normal_strategy_evaluation():
    event = create_event(
        "Xi Jinping resigns after a leadership challenge",
        countries=["China"],
    )
    event.evidence_confidence = .9
    event.published_at = datetime.now(timezone.utc)

    class Client:
        provider_status = {}
        provider_errors = []
        provider_details = {}

        def fetch(self, query=None, limit=100):
            return [event]

        def reset_status(self):
            return None

    decisions = IntelligencePipeline(Client()).run([{
        "question": "Will Xi Jinping be removed before 2027?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.40", "0.60"]',
    }])

    assert len(decisions) == 1
    assert decisions[0].action == StrategyAction.BUY_YES
    assert decisions[0].market_probability == .4


def test_invalid_market_price_is_persisted_only_as_ignored(tmp_path):
    event = create_event(
        "Xi Jinping resigns after a leadership challenge",
        countries=["China"],
    )
    event.evidence_confidence = .9
    event.published_at = datetime.now(timezone.utc)

    class Client:
        provider_status = {}
        provider_errors = []
        provider_details = {}

        def fetch(self, query=None, limit=100):
            return [event]

        def reset_status(self):
            return None

    recorder = PaperTradingRecorder(tmp_path / "history.json")
    decisions = IntelligencePipeline(Client(), paper_trader=recorder).run([{
        "question": "Will Xi Jinping be removed before 2027?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": "malformed",
    }])

    assert len(decisions) == 1
    assert decisions[0].action == StrategyAction.IGNORE
    assert decisions[0].market_probability is None
    assert decisions[0].position_size == 0.0
    persisted = recorder.load()
    assert len(persisted) == 1
    assert persisted[0].market_probability is None
    assert persisted[0].risk_status == "IGNORED"
    assert persisted[0].rationale.startswith("Ignored: invalid market probability")
