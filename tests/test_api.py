# File-Version: 1.1.0
"""Tests for complete active-market retrieval from Polymarket."""

import pytest
import requests

from src.api import PolymarketAPI


def test_get_active_markets_follows_keyset_pagination(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            if len(calls) == 1:
                return {"markets": [{"id": "1"}], "next_cursor": "next"}
            return {"markets": [{"id": "2"}], "next_cursor": None}

    def get(url, params, timeout):
        calls.append((url, dict(params), timeout))
        return Response()

    monkeypatch.setattr("src.api.requests.get", get)

    markets = PolymarketAPI().get_active_markets()

    assert markets == [{"id": "1"}, {"id": "2"}]
    assert calls[0][0].endswith("/markets/keyset")
    assert calls[0][1] == {
        "active": "true", "closed": "false", "limit": 100,
        "order": "volume24hr", "ascending": "false",
    }
    assert calls[1][1]["after_cursor"] == "next"


def test_get_active_markets_honours_total_limit(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            calls.append(True)
            return {
                "markets": [{"id": str(index)} for index in range(10)],
                "next_cursor": "unused",
            }

    monkeypatch.setattr("src.api.requests.get", lambda *args, **kwargs: Response())

    markets = PolymarketAPI().get_active_markets(limit=3)

    assert markets == [{"id": "0"}, {"id": "1"}, {"id": "2"}]
    assert len(calls) == 1


@pytest.mark.parametrize("limit", [0, -1, False, 1.5, "3", None])
def test_get_active_markets_rejects_invalid_limit(limit):
    with pytest.raises(ValueError, match="positive integer"):
        PolymarketAPI().get_active_markets(limit=limit)


def test_get_active_markets_default_is_bounded(monkeypatch):
    requests_seen = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "markets": [{"id": str(index)} for index in range(100)],
                "next_cursor": "more-markets-exist",
            }

    def get(*args, **kwargs):
        requests_seen.append(kwargs)
        return Response()

    monkeypatch.setattr("src.api.requests.get", get)

    markets = PolymarketAPI().get_active_markets()

    assert len(markets) == 100
    assert len(requests_seen) == 1
    assert requests_seen[0]["params"]["order"] == "volume24hr"


def test_get_active_markets_rejects_malformed_payload(monkeypatch):
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"markets": "not-a-list", "next_cursor": None}

    monkeypatch.setattr("src.api.requests.get", lambda *args, **kwargs: Response())

    with pytest.raises(RuntimeError, match="markets must be a list"):
        PolymarketAPI().get_active_markets()


def test_get_active_markets_rejects_repeated_cursor(monkeypatch):
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"markets": [], "next_cursor": "same"}

    monkeypatch.setattr("src.api.requests.get", lambda *args, **kwargs: Response())

    with pytest.raises(RuntimeError, match="repeated cursor"):
        PolymarketAPI().get_active_markets()


def test_get_active_markets_retries_connection_failures(monkeypatch):
    attempts = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"markets": [], "next_cursor": None}

    def get(*args, **kwargs):
        attempts.append(True)
        if len(attempts) < 3:
            raise requests.ConnectionError("temporary failure")
        return Response()

    monkeypatch.setattr("src.api.requests.get", get)
    monkeypatch.setattr("src.api.time.sleep", lambda _seconds: None)

    assert PolymarketAPI().get_active_markets() == []
    assert len(attempts) == 3
