"""
Tests for the RSS intelligence provider.
"""

from datetime import datetime

import requests

from src.intelligence.client import IntelligenceClient
from src.intelligence.providers.base import IntelligenceProvider
from src.intelligence.providers.rss import RSSFeed, RSSProvider
from src.models import GeoPoliticalEvent


RSS_XML = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<rss><channel>
  <item>
    <title>Xi Jinping faces leadership challenge</title>
    <description>China &lt;b&gt;politics&lt;/b&gt; update</description>
    <link>https://example.com/leadership</link>
    <pubDate>Mon, 01 Jan 2026 12:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class FakeProvider(IntelligenceProvider):
    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        return [
            GeoPoliticalEvent(
                title="GDELT event",
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
                source="GDELT",
            )
        ]


def create_provider() -> RSSProvider:
    return RSSProvider(
        [
            RSSFeed(
                name="Test Feed",
                url="https://example.com/rss",
            )
        ]
    )


def test_rss_provider_implements_provider_interface():

    assert isinstance(create_provider(), IntelligenceProvider)


def test_rss_provider_parses_events(monkeypatch):

    monkeypatch.setattr(
        "src.intelligence.providers.rss.requests.get",
        lambda *args, **kwargs: FakeResponse(RSS_XML),
    )

    events = create_provider().fetch()

    assert len(events) == 1
    assert events[0].title == "Xi Jinping faces leadership challenge"
    assert events[0].summary == "China politics update"
    assert events[0].source == "Test Feed"
    assert events[0].source_url == "https://example.com/leadership"


def test_rss_provider_skips_malformed_feed(monkeypatch):

    monkeypatch.setattr(
        "src.intelligence.providers.rss.requests.get",
        lambda *args, **kwargs: FakeResponse(b"not xml"),
    )

    assert create_provider().fetch() == []


def test_rss_provider_skips_network_error(monkeypatch):

    def raise_network_error(*args, **kwargs):
        raise requests.RequestException("Network failure")

    monkeypatch.setattr(
        "src.intelligence.providers.rss.requests.get",
        raise_network_error,
    )

    assert create_provider().fetch() == []


def test_rss_provider_handles_empty_feed(monkeypatch):

    monkeypatch.setattr(
        "src.intelligence.providers.rss.requests.get",
        lambda *args, **kwargs: FakeResponse(
            b"<rss><channel></channel></rss>"
        ),
    )

    assert create_provider().fetch() == []


def test_client_aggregates_rss_and_other_providers(monkeypatch):

    monkeypatch.setattr(
        "src.intelligence.providers.rss.requests.get",
        lambda *args, **kwargs: FakeResponse(RSS_XML),
    )

    events = IntelligenceClient(
        [
            FakeProvider(),
            create_provider(),
        ]
    ).fetch()

    assert [event.source for event in events] == [
        "GDELT",
        "Test Feed",
    ]
