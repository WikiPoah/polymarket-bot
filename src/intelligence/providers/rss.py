# File-Version: 1.0.0
"""
RSS intelligence provider.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
from xml.etree import ElementTree

import requests

from src.config import (
    INTELLIGENCE_USER_AGENT,
    REQUEST_TIMEOUT,
    RSS_FEEDS,
)
from src.intelligence.providers.base import IntelligenceProvider
from src.models import GeoPoliticalEvent


ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"


@dataclass(frozen=True, slots=True)
class RSSFeed:
    """
    Configures a single RSS or Atom feed.
    """

    name: str
    url: str


def _clean_text(value: str | None) -> str:
    """
    Convert RSS HTML content into plain text.
    """

    if not value:
        return ""

    return unescape(
        re.sub(r"<[^>]+>", "", value)
    ).strip()


def _parse_published_at(value: str | None) -> datetime:
    """
    Parse common RSS and Atom publication date formats.
    """

    if value:
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )
            except ValueError:
                pass

    return datetime.now(timezone.utc)


class RSSProvider(IntelligenceProvider):
    """
    Retrieves normalized events from configured RSS and Atom feeds.
    """

    query_sensitive = False

    def __init__(
        self,
        feeds: list[RSSFeed] | None = None,
    ) -> None:

        self._feeds = (
            feeds
            if feeds is not None
            else [
                RSSFeed(**feed)
                for feed in RSS_FEEDS
            ]
        )

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        """
        Retrieve events from every configured feed.

        RSS feeds do not provide a consistent query API, so query and
        sort are accepted for interface compatibility and ignored.
        """

        events: list[GeoPoliticalEvent] = []

        for feed in self._feeds:
            if len(events) >= limit:
                break

            events.extend(
                self._fetch_feed(
                    feed,
                    limit - len(events),
                )
            )

        return events

    def _fetch_feed(
        self,
        feed: RSSFeed,
        limit: int,
    ) -> list[GeoPoliticalEvent]:
        """
        Retrieve and parse one feed without affecting other feeds.
        """

        try:
            response = requests.get(
                feed.url,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": INTELLIGENCE_USER_AGENT,
                },
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except (
            requests.RequestException,
            ElementTree.ParseError,
        ):
            return []

        entries = root.findall(".//item")

        if not entries:
            entries = root.findall(
                f".//{{{ATOM_NAMESPACE}}}entry"
            )

        events: list[GeoPoliticalEvent] = []

        for entry in entries:
            event = self._parse_entry(entry, feed)

            if event is not None:
                events.append(event)

            if len(events) >= limit:
                break

        return events

    def _parse_entry(
        self,
        entry: ElementTree.Element,
        feed: RSSFeed,
    ) -> GeoPoliticalEvent | None:
        """
        Convert one RSS or Atom entry into a raw geopolitical event.
        """

        title = _clean_text(
            self._entry_text(entry, "title")
        )

        if not title:
            return None

        summary = _clean_text(
            self._entry_text(entry, "description")
            or self._entry_text(entry, "summary")
            or self._entry_text(entry, "content")
        )

        url = self._entry_text(entry, "link")

        if not url:
            link = entry.find(
                f"{{{ATOM_NAMESPACE}}}link"
            )
            if link is not None:
                url = link.get("href")

        published_at = _parse_published_at(
            self._entry_text(entry, "pubDate")
            or self._entry_text(entry, "published")
            or self._entry_text(entry, "updated")
        )

        return GeoPoliticalEvent(
            title=title,
            summary=summary,
            category="RSS",
            subcategory="",
            country=None,
            region=None,
            continent=None,
            significance=None,
            confidence=None,
            market_sensitivity=None,
            source_url=url or feed.url,
            published_at=published_at,
            source=feed.name,
        )

    @staticmethod
    def _entry_text(
        entry: ElementTree.Element,
        name: str,
    ) -> str | None:
        """
        Find text from an RSS or Atom element by local name.
        """

        for element in entry.iter():
            if element.tag.rsplit("}", 1)[-1] == name:
                return element.text

        return None
