"""Tests for incremental historical dataset collection."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import requests
import pytest

from src.historical_dataset import (
    GDELTIntelligenceCollector,
    CollectionCheckpoint,
    CollectionRunLock,
    HistoricalIntelligenceItem,
    HistoricalMarketRecord,
    PriceCandle,
    HistoricalDatasetBuilder,
    HistoricalIntelligenceDatasetStore,
    HistoricalMarketCollector,
    HistoricalMarketDatasetStore,
    validate_dataset,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)
YES_TOKEN = "123456789012345678901234567890"
NO_TOKEN = "987654321098765432109876543210"


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
        "id": "m1", "conditionId": "condition-1",
        "question": "Will the event happen?",
        "createdAt": "2026-02-01T00:00:00Z",
        "closedTime": "2026-03-01T00:00:00Z",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]',
        "clobTokenIds": f'["{YES_TOKEN}", "{NO_TOKEN}"]',
        "volume": "1500", "liquidity": "250", "category": "POLITICAL",
    }
    values.update(changes)
    return values


def market_get(calls):
    def get(url, params, **kwargs):
        calls.append((url, params))
        if "gamma-api" in url:
            return Response([market()])
        return Response({"history": [
            {"t": 1769904000, "p": .4},
            {"t": 1771113600, "p": .6},
        ]})
    return get


def test_market_collection_is_incremental_atomic_and_duplicate_free(tmp_path):
    calls = []
    path = tmp_path / "markets.json"
    store = HistoricalMarketDatasetStore(path)
    collector = HistoricalMarketCollector(
        store, http_get=market_get(calls), retries=0, delay_seconds=0,
    )

    first = collector.collect(START, END)
    first_clob_calls = sum("clob" in url for url, _ in calls)
    second = collector.collect(START, END)

    assert first.added == 1
    assert second.added == 0
    assert second.duplicates == 1
    assert len(store.load()) == 1
    assert store.load()[0].has_valid_price_history is True
    assert sum("clob" in url for url, _ in calls) == first_clob_calls
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert not path.with_suffix(".json.tmp").exists()


def test_atomic_store_retries_transient_replace_lock(tmp_path, monkeypatch):
    path = tmp_path / "intelligence.json"
    store = HistoricalIntelligenceDatasetStore(path)
    item = HistoricalIntelligenceItem(
        "id", "title", "GDELT", "https://example.test", START.isoformat(), START.isoformat(),
    )
    original = Path.replace
    attempts = 0

    def replace(source, target):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("temporarily locked")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr("src.historical_dataset.time.sleep", lambda seconds: None)

    store.save([item])

    assert attempts == 3
    assert store.load() == [item]


def test_incomplete_markets_are_skipped_without_corrupting_store(tmp_path):
    def get(url, params, **kwargs):
        return Response([market(question="", clobTokenIds="[]")])

    store = HistoricalMarketDatasetStore(tmp_path / "markets.json")
    result = HistoricalMarketCollector(
        store, http_get=get, retries=0, delay_seconds=0,
    ).collect(START, END)

    assert result.incomplete == 1
    assert result.collected == 0
    assert store.load() == []


def test_failed_market_price_request_is_reported_and_collection_continues(tmp_path):
    def get(url, params, **kwargs):
        if "gamma-api" in url:
            return Response([market()])
        return Response(error=requests.ConnectionError("price unavailable"))

    result = HistoricalMarketCollector(
        HistoricalMarketDatasetStore(tmp_path / "markets.json"),
        http_get=get, retries=1, delay_seconds=0,
    ).collect(START, END)

    assert result.collected == 0
    assert "price unavailable" in result.failures[0]


def test_failed_market_discovery_does_not_mark_checkpoint_complete(tmp_path):
    def get(url, params, **kwargs):
        return Response(error=requests.ConnectTimeout("gamma unavailable"))

    path = tmp_path / "markets.json"
    HistoricalMarketCollector(
        HistoricalMarketDatasetStore(path), http_get=get, retries=0, delay_seconds=0,
    ).collect(START, END)

    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("markets")
    assert state["complete"] is False
    assert state["failures"]


def test_gdelt_windows_preserve_timestamps_and_prevent_duplicates(tmp_path):
    calls = []

    def get(url, params, **kwargs):
        calls.append(params)
        return Response({"articles": [{
            "title": "Leadership transition announced",
            "url": "https://news.example/item",
            "seendate": "20260101T120000Z",
            "domain": "news.example", "sourcecountry": "US", "language": "English",
        }]})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    collector = GDELTIntelligenceCollector(
        store, http_get=get, retries=0, delay_seconds=0,
        window=timedelta(days=1),
    )
    end = START + timedelta(days=2)

    first = collector.collect(START, end)
    second = collector.collect(START, end)
    saved = store.load()

    assert len(calls) == 2
    assert calls[0]["startdatetime"] == "20260101000000"
    assert calls[0]["enddatetime"] == "20260102000000"
    assert first.added == 1 and first.duplicates == 0
    assert second.added == 0
    assert second.duplicates == 0
    assert len(saved) == 1
    assert saved[0].published_at == "2026-01-01T12:00:00+00:00"
    assert saved[0].available_at == saved[0].published_at


def test_failed_gdelt_window_is_recorded_and_later_window_succeeds(tmp_path):
    attempts = 0

    def get(url, params, **kwargs):
        nonlocal attempts
        attempts += 1
        if params["startdatetime"] == "20260101000000":
            return Response(error=requests.Timeout("window timeout"))
        return Response({"articles": [{
            "title": "Historical event", "url": "https://example.test/two",
            "seendate": "20260102T010000Z",
        }]})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    result = GDELTIntelligenceCollector(
        store, http_get=get, retries=1, delay_seconds=0,
        window=timedelta(days=1),
    ).collect(START, START + timedelta(days=2))

    assert attempts == 3
    assert len(result.failures) == 1
    assert result.added == 1
    assert len(store.load()) == 1


def test_gdelt_stops_after_consecutive_failures_and_can_resume(tmp_path):
    calls = 0

    def get(url, params, **kwargs):
        nonlocal calls
        calls += 1
        return Response(error=requests.Timeout("offline"))

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=0, delay_seconds=0,
        window=timedelta(days=1), max_consecutive_failures=2,
    )
    collector.collect(START, START + timedelta(days=10))

    assert calls == 2
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("intelligence")
    assert state["complete"] is False
    assert len(state["failures"]) == 2


def test_builder_writes_six_month_summary(tmp_path):
    market_store = HistoricalMarketDatasetStore(tmp_path / "markets.json")
    intelligence_store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    markets = HistoricalMarketCollector(
        market_store, http_get=market_get([]), retries=0, delay_seconds=0,
    )

    def gdelt_get(url, params, **kwargs):
        return Response({"articles": [{
            "title": "Event", "url": f"https://example.test/{params['startdatetime']}",
            "seendate": params["startdatetime"] + "Z",
        }]})

    intelligence = GDELTIntelligenceCollector(
        intelligence_store, http_get=gdelt_get, retries=0, delay_seconds=0,
        window=timedelta(days=31),
    )
    summary_path = tmp_path / "summary.json"

    summary = HistoricalDatasetBuilder(markets, intelligence, summary_path).build(START, END)

    assert summary.markets_collected == 1
    assert summary.markets_with_valid_price_history == 1
    assert summary.intelligence_records == 6
    assert summary.intelligence_coverage_windows == 6
    assert summary.missing_data["markets_without_price_history"] == 0
    assert summary.missing_data["market_discovery_incomplete"] == 0
    assert summary.missing_data["intelligence_windows_missing"] == 0
    assert json.loads(summary_path.read_text(encoding="utf-8"))["start"] == START.isoformat()


def test_interrupted_intelligence_collection_resumes_completed_windows(tmp_path):
    calls = []
    interrupted = True

    def get(url, params, **kwargs):
        nonlocal interrupted
        calls.append(params["startdatetime"])
        if params["startdatetime"] == "20260102000000" and interrupted:
            interrupted = False
            raise KeyboardInterrupt
        return Response({"articles": [{
            "title": "Event", "url": f"https://example.test/{params['startdatetime']}",
            "seendate": params["startdatetime"] + "Z",
        }]})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    collector = GDELTIntelligenceCollector(
        store, http_get=get, retries=0, delay_seconds=0,
        window=timedelta(days=1),
    )
    end = START + timedelta(days=3)

    with pytest.raises(KeyboardInterrupt):
        collector.collect(START, end)
    assert len(store.load()) == 1
    assert CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "intelligence"
    )["completed_windows"] == [
        "2026-01-01T00:00:00+00:00..2026-01-02T00:00:00+00:00"
    ]

    collector.collect(START, end)

    assert len(store.load()) == 3
    assert calls.count("20260101000000") == 1


def test_partial_failures_and_progress_are_checkpointed(tmp_path):
    progress = []

    def get(url, params, **kwargs):
        if "gamma-api" in url:
            return Response([market(id="bad"), market(id="good")])
        if params["market"] == YES_TOKEN:
            return Response(error=requests.Timeout("temporary outage"))
        return Response({"history": [{"t": 1769904000, "p": .5}]})

    collector = HistoricalMarketCollector(
        HistoricalMarketDatasetStore(tmp_path / "markets.json"),
        http_get=get, retries=0, delay_seconds=0, workers=1,
        progress=progress.append,
    )
    result = collector.collect(START, END)
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("markets")

    assert result.failures
    assert state["failures"] == list(result.failures)
    assert state["markets_processed"] == 2
    assert progress[-1]["markets_processed"] == 2
    assert progress[-1]["markets_total"] == 2
    assert "elapsed_seconds" in progress[-1]


def test_checkpoint_store_and_upserts_prevent_duplicates(tmp_path):
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    checkpoint.update("markets", markets_processed=3, failures=["one"])
    checkpoint.update("intelligence", windows_completed=2)
    assert checkpoint.section("markets")["markets_processed"] == 3
    assert checkpoint.section("intelligence")["windows_completed"] == 2

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    item = HistoricalIntelligenceItem(
        "id", "title", "GDELT", "https://example.test", START.isoformat(), START.isoformat(),
    )
    store.upsert([item, item])
    assert len(store.load()) == 1


def test_collection_run_lock_prevents_concurrent_writer(tmp_path):
    first = CollectionRunLock(tmp_path / "collection.lock")
    second = CollectionRunLock(tmp_path / "collection.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_validation_detects_candle_and_intelligence_coverage_issues():
    record = HistoricalMarketRecord(
        market_id="m", condition_id=None, question="Question?",
        created_at=START.isoformat(), closed_at=(START + timedelta(days=5)).isoformat(),
        outcomes=("Yes", "No"), token_ids={"YES": YES_TOKEN, "NO": NO_TOKEN},
        resolution_outcome="YES",
        price_history={
            "YES": (
                PriceCandle((START + timedelta(days=3)).isoformat(), .6),
                PriceCandle(START.isoformat(), .4),
                PriceCandle(START.isoformat(), .4),
            ),
        },
    )
    report = validate_dataset(
        [record, record], [], START, START + timedelta(days=3), timedelta(days=1),
    )

    assert report.duplicate_markets == 1
    assert report.markets_with_unordered_candles == 2
    assert report.markets_with_duplicate_candles == 2
    assert report.markets_with_missing_periods == 2
    assert report.incomplete_outcomes == 2
    assert report.intelligence_windows_missing == 3
