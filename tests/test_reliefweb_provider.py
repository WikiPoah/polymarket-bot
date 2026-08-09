# File-Version: 1.0.0
"""Tests for normalized ReliefWeb intelligence ingestion."""

import requests
import pytest

from src.intelligence.exceptions import IntelligenceProviderError
from src.intelligence.providers.base import IntelligenceProvider
from src.intelligence.providers.reliefweb import ReliefWebProvider


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": [{
                "fields": {
                    "title": "Humanitarian update for Ukraine",
                    "body": "Aid agencies report new displacement.",
                    "url": "https://reliefweb.int/report/example",
                    "date": {"created": "2026-08-01T12:00:00Z"},
                    "primary_country": {"name": "Ukraine"},
                },
            }],
        }


def test_reliefweb_provider_normalizes_reports(monkeypatch):
    monkeypatch.setattr(
        "src.intelligence.providers.reliefweb.requests.get",
        lambda *args, **kwargs: Response(),
    )

    provider = ReliefWebProvider()
    events = provider.fetch(query="Ukraine", limit=5)

    assert isinstance(provider, IntelligenceProvider)
    assert len(events) == 1
    assert events[0].source == "ReliefWeb"
    assert events[0].country == "Ukraine"
    assert events[0].countries == ["Ukraine"]
    assert events[0].locations == ["Ukraine"]
    assert events[0].published_at.isoformat() == "2026-08-01T12:00:00+00:00"


def test_reliefweb_provider_uses_configured_appname(monkeypatch):
    requests_seen = []

    def get(*args, **kwargs):
        requests_seen.append(kwargs)
        return Response()

    monkeypatch.setattr(
        "src.intelligence.providers.reliefweb.RELIEFWEB_APPNAME",
        "approved-application-name",
    )
    monkeypatch.setattr(
        "src.intelligence.providers.reliefweb.requests.get",
        get,
    )

    ReliefWebProvider().fetch()

    assert requests_seen[0]["params"]["appname"] == "approved-application-name"


def test_reliefweb_provider_reports_network_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.RequestException("offline")

    monkeypatch.setattr("src.intelligence.providers.reliefweb.requests.get", fail)
    with pytest.raises(IntelligenceProviderError):
        ReliefWebProvider().fetch()
