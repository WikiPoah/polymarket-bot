# File-Version: 1.0.1
"""
Tests for the intelligence provider interface and aggregation.
"""

from datetime import datetime, timezone

import pytest

from src.intelligence.client import IntelligenceClient
from src.intelligence.evidence import get_source_reliability
from src.intelligence.exceptions import IntelligenceProviderError
from src.intelligence.providers.base import IntelligenceProvider
from src.intelligence.providers.gdelt import GDELTProvider
from src.intelligence.providers.rss import RSSProvider
from src.models import GeoPoliticalEvent


def create_event(title: str) -> GeoPoliticalEvent:
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
        published_at=datetime.now(),
    )


class FakeProvider(IntelligenceProvider):
    """
    Deterministic provider used to test client aggregation.
    """

    def __init__(self, events: list[GeoPoliticalEvent]) -> None:
        self._events = events

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        return self._events


class FailingProvider(IntelligenceProvider):
    """
    Provider that simulates an unavailable external source.
    """

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        raise IntelligenceProviderError("Provider unavailable")


class CountingProvider(FakeProvider):
    def __init__(self, events, query_sensitive=True):
        super().__init__(events)
        self.query_sensitive = query_sensitive
        self.calls = []

    def fetch(self, query=None, limit=100, sort="recent"):
        self.calls.append((query, limit, sort))
        return super().fetch(query, limit, sort)


def test_provider_interface_requires_fetch_implementation():

    with pytest.raises(TypeError):
        IntelligenceProvider()


def test_gdelt_provider_implements_provider_interface():

    assert isinstance(GDELTProvider(), IntelligenceProvider)


def test_gdelt_provider_returns_normalized_events(monkeypatch):

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": [
                    {
                        "title": "Leadership event",
                        "summary": "Summary",
                        "category": "POLITICAL",
                        "subcategory": "",
                        "geo": {
                            "country": "China",
                            "region": None,
                            "continent": None,
                        },
                        "metrics": {
                            "significance": 0.9,
                            "confidence": 0.8,
                            "market_sensitivity": 0.7,
                        },
                        "url": "https://example.com/event",
                        "processed_at": "2026-01-01T00:00:00Z",
                    }
                ]
            }

    class FakeClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def get(self, *args, **kwargs) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr(
        "src.intelligence.providers.gdelt.GDELT_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "src.intelligence.providers.gdelt.httpx.Client",
        FakeClient,
    )

    events = GDELTProvider().fetch(query="leadership")

    assert len(events) == 1
    assert isinstance(events[0], GeoPoliticalEvent)
    assert events[0].title == "Leadership event"


def test_rss_provider_implements_provider_interface():

    assert isinstance(RSSProvider(), IntelligenceProvider)


def test_client_aggregates_events_from_multiple_providers():

    first_event = create_event("First event")
    second_event = create_event("Second event")

    client = IntelligenceClient(
        [
            FakeProvider([first_event]),
            FakeProvider([second_event]),
        ]
    )

    events = client.fetch(query="test", limit=10)

    assert events == [first_event, second_event]
    assert all(
        isinstance(event, GeoPoliticalEvent)
        for event in events
    )


def test_client_reuses_identical_provider_query_until_reset():
    provider = CountingProvider([create_event("Cached event")])
    client = IntelligenceClient([provider])

    first = client.fetch(query="Iran", limit=10)
    second = client.fetch(query="Iran", limit=10)

    assert len(provider.calls) == 1
    assert first == second
    assert first[0] is not second[0]

    client.reset_status()
    client.fetch(query="Iran", limit=10)

    assert len(provider.calls) == 2


def test_client_reuses_query_insensitive_provider_across_market_queries():
    provider = CountingProvider(
        [create_event("Shared feed event")],
        query_sensitive=False,
    )
    client = IntelligenceClient([provider])

    client.fetch(query="Iran")
    client.fetch(query="China")

    assert len(provider.calls) == 1


def test_client_archives_only_fresh_provider_results():
    archived = []
    provider = CountingProvider([create_event("Archived once")])
    client = IntelligenceClient([provider], event_sink=archived.extend)

    client.fetch(query="Iran")
    client.fetch(query="Iran")

    assert len(archived) == 1


def test_source_reliability_is_configurable():

    assert get_source_reliability("GDELT") == 0.90
    assert get_source_reliability("unknown source") == 0.50
    assert get_source_reliability("UN News") == 0.85
    assert get_source_reliability("ReliefWeb") == 0.85


def test_client_deduplicates_and_combines_sources():

    first_event = create_event("Xi Jinping leadership rumours")
    first_event.source = "GDELT"
    first_event.source_url = "https://gdelt.example/event"

    second_event = create_event("Xi Jinping leadership rumours")
    second_event.source = "BBC World"
    second_event.source_url = "https://bbc.example/event"

    events = IntelligenceClient(
        [
            FakeProvider([first_event]),
            FakeProvider([second_event]),
        ]
    ).fetch()

    assert len(events) == 1
    assert events[0].supporting_sources == [
        "GDELT",
        "BBC World",
    ]
    assert events[0].supporting_source_count == 2
    assert events[0].evidence_confidence > 0.90


def test_single_source_event_remains_valid():

    event = create_event("Single source report")
    event.source = "BBC World"

    events = IntelligenceClient(
        [FakeProvider([event])]
    ).fetch()

    assert len(events) == 1
    assert events[0].supporting_source_count == 1
    assert events[0].evidence_confidence == 0.80


def test_client_continues_after_provider_error():

    event = create_event("Available provider event")

    client = IntelligenceClient(
        [
            FailingProvider(),
            FakeProvider([event]),
        ]
    )
    events = client.fetch()

    assert events == [event]
    assert client.provider_status == {
        "FailingProvider": "ERROR",
        "FakeProvider": "OK",
    }
    assert client.provider_errors == ["FailingProvider: Provider unavailable"]
    assert client.provider_details["FailingProvider"]["status"] == "ERROR"


def test_client_tracks_provider_data_freshness():
    event = create_event("Fresh event")
    client = IntelligenceClient([FakeProvider([event])])

    client.fetch()

    details = client.provider_details["FakeProvider"]
    assert details["status"] == "OK"
    assert details["last_successful_run"] is not None
    assert details["last_data_received"] == event.published_at.replace(
        tzinfo=timezone.utc,
    ).isoformat()
    assert details["event_age_seconds"] >= 0
