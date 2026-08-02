"""
Tests for the intelligence provider interface and aggregation.
"""

from datetime import datetime

import pytest

from src.intelligence.client import IntelligenceClient
from src.intelligence.providers.base import IntelligenceProvider
from src.intelligence.providers.gdelt import GDELTProvider
from src.intelligence.providers.news_api import NewsAPIProvider
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


def test_placeholder_providers_implement_provider_interface():

    assert isinstance(RSSProvider(), IntelligenceProvider)
    assert isinstance(NewsAPIProvider(), IntelligenceProvider)


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
