# File-Version: 1.0.0
"""Regression tests for the read-only historical data coverage probe."""

from datetime import datetime, timezone

import requests

from src.coverage_probe import HistoricalCoverageProbe, _timestamp


YES_TOKEN = "123456789012345678901234567890"
NO_TOKEN = "987654321098765432109876543210"


def test_gdelt_compact_timestamps_are_supported_on_python_310():
    expected = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)

    assert _timestamp("20260101T123000Z") == expected
    assert _timestamp("20260101123000Z") == expected


class Response:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.payload


def market(**changes):
    values = {
        "id": "m1", "question": "Will the event happen?",
        "createdAt": "2026-01-01T00:00:00Z",
        "closedTime": "2026-02-01T00:00:00Z",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]',
        "clobTokenIds": f'["{YES_TOKEN}", "{NO_TOKEN}"]',
        "volume": "1200", "liquidity": "300",
    }
    values.update(changes)
    return values


def successful_get(url, params, **kwargs):
    if "gamma-api" in url:
        return Response([market()])
    if "clob" in url:
        assert "interval" not in params
        assert params["startTs"] == 1767225600
        assert params["endTs"] == 1769990400
        shift = 0 if params["market"] == YES_TOKEN else 60
        return Response({"history": [{"t": 1767225600 + shift, "p": .4}]})
    if "gdeltproject" in url:
        return Response({"articles": [{"seendate": "20260102T120000Z"}]})
    return Response({"data": [{"fields": {"date": {"created": "2026-01-03T00:00:00Z"}}}]})


def test_successful_collection_reports_market_and_intelligence_coverage():
    probe = HistoricalCoverageProbe(successful_get)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    report = probe.run(20, start, datetime(2026, 7, 1, tzinfo=timezone.utc))

    assert report.polymarket.markets_checked == 1
    assert report.polymarket.valid_historical_prices == 1
    assert report.polymarket.coverage_percentage == 100.0
    assert report.polymarket.markets[0].resolution_outcome == "Yes"
    assert report.polymarket.markets[0].price_start == "2026-01-01T00:00:00+00:00"
    assert report.intelligence.gdelt.valid_timestamps == 1
    assert report.intelligence.reliefweb.valid_timestamps == 1
    assert report.six_month_backtest_feasible is True


def test_missing_data_and_incomplete_market_are_reported():
    incomplete = market(
        createdAt=None, closedTime=None, outcomePrices="[]",
        clobTokenIds=f'["{YES_TOKEN}"]', volume=None, liquidity=None,
    )

    def get(url, params, **kwargs):
        if "gamma-api" in url:
            return Response([incomplete, "not-a-market"])
        if "clob" in url:
            return Response({"history": []})
        return Response({"articles": []} if "gdelt" in url else {"data": []})

    report = HistoricalCoverageProbe(get).probe_polymarket(20)
    item = report.markets[0]

    assert report.markets_returned == 2
    assert report.markets_checked == 1
    assert report.coverage_percentage == 0.0
    assert "creation_timestamp" in item.missing_fields
    assert "no_token_id" in item.missing_fields
    assert "yes_price_history" in item.missing_fields
    assert "resolution_outcome" in item.missing_fields
    assert item.volume_available is False
    assert item.liquidity_available is False


def test_api_failures_do_not_abort_probe():
    failure = requests.ConnectionError("offline")

    def get(url, params, **kwargs):
        if "gamma-api" in url or "gdelt" in url or "reliefweb" in url:
            return Response(error=failure)
        raise AssertionError("unexpected request")

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    report = HistoricalCoverageProbe(get).run(
        25, start, datetime(2026, 7, 1, tzinfo=timezone.utc),
    )

    assert report.polymarket.markets_checked == 0
    assert report.polymarket.api_failures
    assert report.intelligence.gdelt.api_failures == ["offline"]
    assert report.intelligence.reliefweb.api_failures == ["offline"]
    assert report.six_month_backtest_feasible is False


def test_one_token_api_failure_is_preserved_on_market_record():
    def get(url, params, **kwargs):
        if "gamma-api" in url:
            return Response([market()])
        if params["market"] == YES_TOKEN:
            return Response({"history": [{"t": 1767225600, "p": .4}]})
        return Response(error=requests.Timeout("timed out"))

    report = HistoricalCoverageProbe(get).probe_polymarket(20)

    assert report.valid_historical_prices == 0
    assert report.markets[0].price_available == {"YES": True, "NO": False}
    assert report.markets[0].api_failures == ["NO price history failed: timed out"]


def test_invalid_token_ids_are_not_sent_to_clob():
    calls = []

    def get(url, params, **kwargs):
        calls.append(url)
        if "gamma-api" in url:
            return Response([market(clobTokenIds='["not-a-token", "0"]')])
        raise AssertionError("invalid token should not be requested")

    report = HistoricalCoverageProbe(get).probe_polymarket(20)

    assert calls == ["https://gamma-api.polymarket.com/markets"]
    assert report.valid_historical_prices == 0
    assert "yes_invalid_token_id" in report.markets[0].missing_fields
    assert "no_invalid_token_id" in report.markets[0].missing_fields


def test_non_yes_no_outcomes_map_to_tokens_by_position():
    over_token = "111111111111111111111111111111"
    under_token = "222222222222222222222222222222"

    def get(url, params, **kwargs):
        if "gamma-api" in url:
            return Response([market(
                outcomes='["Over", "Under"]',
                outcomePrices='["0", "1"]',
                clobTokenIds=f'["{over_token}", "{under_token}"]',
            )])
        return Response({"history": [{"t": 1767225600, "p": .5}]})

    report = HistoricalCoverageProbe(get).probe_polymarket(20)
    item = report.markets[0]

    assert item.token_ids == {"OVER": over_token, "UNDER": under_token}
    assert item.price_available == {"OVER": True, "UNDER": True}
    assert report.valid_historical_prices == 1
    assert report.coverage_percentage == 100.0


def test_sample_size_is_bounded():
    probe = HistoricalCoverageProbe(successful_get)
    try:
        probe.probe_polymarket(10)
    except ValueError as error:
        assert "between 20 and 50" in str(error)
    else:
        raise AssertionError("expected invalid sample size to fail")
