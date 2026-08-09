# File-Version: 1.0.0
"""ReliefWeb public API provider for normalized humanitarian intelligence."""

from datetime import datetime

import requests

from src.config import (
    INTELLIGENCE_USER_AGENT,
    RELIEFWEB_API_URL,
    RELIEFWEB_APPNAME,
    REQUEST_TIMEOUT,
)
from src.intelligence.exceptions import IntelligenceProviderError
from src.intelligence.providers.base import IntelligenceProvider
from src.models import GeoPoliticalEvent


class ReliefWebProvider(IntelligenceProvider):
    """Retrieve reports from the UN OCHA ReliefWeb API."""

    def fetch(
        self,
        query: str | None = None,
        limit: int = 100,
        sort: str = "recent",
    ) -> list[GeoPoliticalEvent]:
        params = {
            "appname": RELIEFWEB_APPNAME,
            "limit": min(limit, 100),
            "sort[]": "date.created:desc",
            "fields[include][]": [
                "title", "body", "url", "date.created", "primary_country.name",
            ],
        }
        if query:
            params["query[value]"] = query
        try:
            response = requests.get(
                RELIEFWEB_API_URL,
                params=params,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": INTELLIGENCE_USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as error:
            raise IntelligenceProviderError("ReliefWeb request failed") from error

        records = payload.get("data", []) if isinstance(payload, dict) else []
        events = []
        for record in records:
            fields = record.get("fields", {}) if isinstance(record, dict) else {}
            title = fields.get("title")
            created = fields.get("date", {}).get("created")
            if not title or not created:
                continue
            try:
                published_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                continue
            country = fields.get("primary_country", {}).get("name")
            events.append(GeoPoliticalEvent(
                title=title,
                summary=fields.get("body", ""),
                category="HUMANITARIAN",
                subcategory="",
                country=country,
                region=None,
                continent=None,
                significance=None,
                confidence=None,
                market_sensitivity=None,
                source_url=fields.get("url", ""),
                published_at=published_at,
                source="ReliefWeb",
                countries=[country] if country else [],
                locations=[country] if country else [],
            ))
        return events
