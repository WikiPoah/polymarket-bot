# File-Version: 1.3.0
"""Tests for incremental historical dataset collection."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import requests
import pytest

from src.persistence import PersistenceCorruptionError

from src.historical_dataset import (
    GDELTIntelligenceCollector,
    CollectionResult,
    CollectionCheckpoint,
    CollectionManifestStore,
    CollectionRunLock,
    HistoricalIntelligenceItem,
    HistoricalIntelligenceManifestStore,
    HistoricalIntelligenceProviderSpec,
    MultiProviderHistoricalIntelligenceCollector,
    MediaCloudHistoricalIntelligenceCollector,
    HistoricalMarketRecord,
    HistoricalMarketMetadata,
    PriceCandle,
    HistoricalDatasetBuilder,
    HistoricalIntelligenceDatasetStore,
    HistoricalMarketCollector,
    HistoricalMarketDatasetStore,
    HistoricalMarketSelector,
    HistoricalMarketUniverseStore,
    ReliefWebHistoricalIntelligenceCollector,
    MarketSelectionReport,
    HistoricalDatasetReplayAdapter,
    PublicDataRequestError,
    _classify_clob_failure,
    _legacy_market_exclusions,
    _normalized_story_url,
    validate_dataset,
    analyze_market_universe,
    historical_intelligence_status_report,
    load_event_focused_pilot_manifest,
    freeze_pilot_collection_reference,
    pilot_intelligence_status_report,
    _strict_geopolitical_category,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)
YES_TOKEN = "123456789012345678901234567890"
NO_TOKEN = "987654321098765432109876543210"


class Response:
    def __init__(self, payload=None, error=None, headers=None):
        self.payload = payload
        self.error = error
        self.headers = headers or {}

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


def test_dataset_upsert_preserves_existing_malformed_state(tmp_path):
    path = tmp_path / "markets.json"
    original = b'{"records": [broken'
    path.write_bytes(original)
    store = HistoricalMarketDatasetStore(path)

    with pytest.raises(PersistenceCorruptionError, match="versioned dataset file"):
        store.upsert([])

    assert path.read_bytes() == original


def test_checkpoint_update_preserves_existing_malformed_state(tmp_path):
    path = tmp_path / "checkpoint.json"
    original = b'{"markets": broken'
    path.write_bytes(original)
    checkpoint = CollectionCheckpoint(path)

    with pytest.raises(PersistenceCorruptionError, match="collection checkpoint"):
        checkpoint.update("markets", discovery_complete=True)

    assert path.read_bytes() == original


def test_checkpoint_rejects_invalid_section_structure(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text(
        json.dumps({"version": 1, "markets": [], "intelligence": {}}),
        encoding="utf-8",
    )

    with pytest.raises(PersistenceCorruptionError, match="section 'markets' is invalid"):
        CollectionCheckpoint(path).load()


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


def test_keyset_market_discovery_uses_scheduled_end_and_stable_denominator(tmp_path):
    calls = []
    february = market(id="feb", closedTime="2026-02-15T00:00:00Z")
    march = market(id="mar", closedTime="2026-03-15T00:00:00Z")

    def get(url, params, **kwargs):
        calls.append((url, dict(params)))
        if "gamma-api" in url:
            if "after_cursor" not in params:
                return Response({"markets": [february], "next_cursor": "page-2"})
            return Response({"markets": [march], "next_cursor": None})
        return Response({"history": [{"t": 1769904000, "p": .5}]})

    store = HistoricalMarketDatasetStore(tmp_path / "markets.json")
    result = HistoricalMarketCollector(
        store, http_get=get, retries=0, delay_seconds=0, page_size=1,
    ).collect(START, END)
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("markets")

    assert result.collected == 2
    assert calls[0][0].endswith("/markets/keyset")
    assert calls[0][1]["order"] == "closedTime"
    assert calls[0][1]["end_date_min"] == START.isoformat()
    assert calls[1][1]["after_cursor"] == "page-2"
    assert state["discovered_market_denominator"] == 2
    assert state["discovery_complete"] is True


def test_gdelt_failure_is_persisted_in_retry_queue_until_success(tmp_path):
    failing = True

    def get(url, params, **kwargs):
        nonlocal failing
        if failing:
            return Response(error=requests.Timeout("later"))
        return Response({"articles": []})

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=0, delay_seconds=0, max_consecutive_failures=1,
    )
    end = START + timedelta(days=1)
    collector.collect(START, end)
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    assert len(checkpoint.section("intelligence")["retry_queue"]) == 1

    failing = False
    collector.collect(START, end)
    assert checkpoint.section("intelligence")["retry_queue"] == []
    assert checkpoint.section("intelligence")["complete"] is True


def test_gdelt_429_uses_extended_rate_limit_backoff(tmp_path):
    sleeps = []
    attempts = 0

    def get(url, params, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "20"
            return Response(error=requests.HTTPError("rate limited", response=response))
        return Response({"articles": []})

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=1, delay_seconds=0, sleep=sleeps.append,
        max_consecutive_failures=1, rate_limit_backoff_seconds=30,
    )

    result = collector.collect(START, START + timedelta(days=1))

    assert result.failures == ()
    assert attempts == 2
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(30, abs=.1)


def test_gdelt_429_global_cooldown_survives_persistent_failure(tmp_path):
    sleeps = []
    calls = []

    def get(url, params, **kwargs):
        calls.append(params["startdatetime"])
        if params["startdatetime"] == "20260101000000":
            response = requests.Response()
            response.status_code = 429
            return Response(error=requests.HTTPError("rate limited", response=response))
        return Response({"articles": []})

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=1, delay_seconds=0, sleep=sleeps.append,
        rate_limit_backoff_seconds=60,
        maximum_rate_limit_backoff_seconds=60,
        max_consecutive_failures=3, jitter=lambda low, high: low,
    )

    collector.collect(START, START + timedelta(days=2))
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("intelligence")

    assert calls == ["20260101000000", "20260101000000", "20260102000000"]
    assert len(sleeps) == 2
    assert all(item == pytest.approx(60, abs=.1) for item in sleeps)
    assert state["rate_limit_events_this_run"] == 2
    assert len(state["retry_queue"]) == 1
    assert state["completed_windows"] == [
        "2026-01-02T00:00:00+00:00..2026-01-03T00:00:00+00:00"
    ]


def test_gdelt_retry_after_overrides_jittered_cooldown(tmp_path):
    sleeps = []
    attempts = 0

    def get(url, params, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "95"
            return Response(error=requests.HTTPError("rate limited", response=response))
        return Response({"articles": []})

    result = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=1, delay_seconds=0, sleep=sleeps.append,
        rate_limit_backoff_seconds=60,
        maximum_rate_limit_backoff_seconds=120,
        jitter=lambda low, high: low,
    ).collect(START, START + timedelta(days=1))

    assert result.failures == ()
    assert sleeps == pytest.approx([95], abs=.1)


def test_gdelt_batch_pauses_after_multiple_persistent_429s(tmp_path):
    calls = []

    def get(url, params, **kwargs):
        calls.append(params["startdatetime"])
        response = requests.Response()
        response.status_code = 429
        return Response(error=requests.HTTPError("rate limited", response=response))

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=0, delay_seconds=0, sleep=lambda seconds: None,
        rate_limit_backoff_seconds=60,
        maximum_rate_limit_backoff_seconds=60,
        max_rate_limit_failures_per_run=2, jitter=lambda low, high: low,
    )

    collector.collect(START, START + timedelta(days=5))
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("intelligence")

    assert calls == ["20260101000000", "20260102000000"]
    assert state["persistent_rate_limit_failures_this_run"] == 2
    assert state["rate_limit_pause_triggered"] is True
    assert len(state["retry_queue"]) == 2


def test_intelligence_manifest_freezes_provider_query_partition_and_policy(tmp_path):
    store = HistoricalIntelligenceManifestStore(tmp_path / "intelligence-manifest.json")
    providers = (
        HistoricalIntelligenceProviderSpec(
            "GDELT", "geopolitics", "gdelt.seendate_first_observed",
        ),
        HistoricalIntelligenceProviderSpec(
            "ReliefWeb", "", "reliefweb.date.created",
        ),
    )

    partitions = store.create(START, START + timedelta(days=2), providers)
    partition = partitions[0]
    store.update_status(partition.partition_id, "complete", records=3)

    assert len(partitions) == 4
    assert store.create(START, START + timedelta(days=2), providers) == partitions
    assert store.coverage()[partition.provider]["complete"] == 1
    with pytest.raises(ValueError, match="different plan"):
        store.create(START, START + timedelta(days=3), providers)


def test_event_focused_pilot_manifest_freezes_shared_collection_bounds(tmp_path):
    path = tmp_path / "pilot.json"
    path.write_text(json.dumps({
        "status": "planned", "pilot_id": "pilot",
        "summary": {"selected_clusters": 2, "included_markets": 3},
        "clusters": [
            {
                "cluster_id": "a", "market_ids": ["1", "2"],
                "pre_event_intelligence_start": "2026-02-01T00:00:00+00:00",
                "replay_end": "2026-03-01T00:00:00+00:00",
            },
            {
                "cluster_id": "b", "market_ids": ["3"],
                "pre_event_intelligence_start": "2026-02-15T00:00:00+00:00",
                "replay_end": "2026-04-01T00:00:00+00:00",
            },
        ],
    }))

    pilot = load_event_focused_pilot_manifest(path)
    frozen = tmp_path / "output" / "pilot_collection_plan.json"
    freeze_pilot_collection_reference(pilot, frozen)
    freeze_pilot_collection_reference(pilot, frozen)

    assert pilot["_collection_start"] == "2026-02-01T00:00:00+00:00"
    assert pilot["_collection_end"] == "2026-04-01T00:00:00+00:00"
    assert json.loads(frozen.read_text())["market_ids"] == ["1", "2", "3"]


def test_pilot_status_validates_shared_day_provenance_and_timestamp_safety(tmp_path):
    pilot_path = tmp_path / "pilot.json"
    pilot_path.write_text(json.dumps({
        "status": "planned", "pilot_id": "pilot",
        "summary": {"selected_clusters": 1, "included_markets": 1},
        "clusters": [{
            "cluster_id": "a", "market_ids": ["1"],
            "pre_event_intelligence_start": START.isoformat(),
            "replay_end": (START + timedelta(days=1)).isoformat(),
        }],
    }))
    pilot = load_event_focused_pilot_manifest(pilot_path)
    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    manifest = HistoricalIntelligenceManifestStore(tmp_path / "intelligence-manifest.json")
    providers = (HistoricalIntelligenceProviderSpec(
        "GDELT", "geopolitics", "gdelt.seendate_first_observed",
    ),)
    partition = manifest.create(START, START + timedelta(days=1), providers)[0]
    root = f"{partition.start}..{partition.end}"
    store.save([HistoricalIntelligenceItem(
        "id", "Event", "GDELT", "https://example.test",
        START.isoformat(), START.isoformat(), metadata={
            "historical_provider": "GDELT", "root_partition": root,
            "partition_start": partition.start, "partition_end": partition.end,
            "availability_timestamp_policy": "gdelt.seendate_first_observed",
        },
    )])
    manifest.update_status(partition.partition_id, "complete", records=1)

    status = pilot_intelligence_status_report(pilot, manifest, store, checkpoint)

    assert status["missing_days"] == {"GDELT": []}
    assert status["validation"]["records_checked"] == 1
    assert status["validation"]["invalid_provenance_records"] == 0
    assert status["validation"]["unsafe_timestamp_records"] == 0
    assert status["ready_for_replay"] is True


def test_gdelt_adaptively_splits_saturated_daily_window_and_tracks_provenance(tmp_path):
    calls = []

    def get(url, params, **kwargs):
        calls.append(dict(params))
        start = params["startdatetime"]
        if start == "20260101000000" and params["enddatetime"] == "20260102000000":
            return Response({"articles": [{}, {}]})
        seen = "20260101T060000Z" if start.endswith("000000") else "20260101T180000Z"
        return Response({"articles": [{
            "title": f"Event {start}", "url": f"https://example.test/{start}",
            "seendate": seen,
        }]})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    collector = GDELTIntelligenceCollector(
        store, http_get=get, retries=0, delay_seconds=0, result_limit=2,
        minimum_window=timedelta(hours=12),
    )

    result = collector.collect(START, START + timedelta(days=1))
    records = store.load()

    assert result.added == 2
    assert len(calls) == 3
    assert all(item.available_at == item.published_at for item in records)
    assert all(item.metadata["root_partition"].startswith(START.isoformat()) for item in records)
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("intelligence")
    assert len(state["adaptive_partitions"][state["completed_windows"][0]]) == 2


def test_gdelt_resumes_only_failed_adaptive_leaf(tmp_path):
    calls = []
    fail_second_leaf = True

    def get(url, params, **kwargs):
        nonlocal fail_second_leaf
        key = (params["startdatetime"], params["enddatetime"])
        calls.append(key)
        if key == ("20260101000000", "20260102000000"):
            return Response({"articles": [{}, {}]})
        if key[0] == "20260101120000" and fail_second_leaf:
            fail_second_leaf = False
            return Response(error=requests.Timeout("retry leaf"))
        seen = "20260101T060000Z" if key[0].endswith("000000") else "20260101T180000Z"
        return Response({"articles": [{
            "title": seen, "url": f"https://example.test/{seen}", "seendate": seen,
        }]})

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=0, delay_seconds=0, result_limit=2,
        minimum_window=timedelta(hours=12),
    )
    collector.collect(START, START + timedelta(days=1))
    collector.collect(START, START + timedelta(days=1))

    assert calls.count(("20260101000000", "20260102000000")) == 1
    assert calls.count(("20260101000000", "20260101120000")) == 1
    assert calls.count(("20260101120000", "20260102000000")) == 2
    assert len(collector.store.load()) == 2


def test_gdelt_request_budget_defers_and_resumes_without_refetch(tmp_path):
    calls = []

    def get(url, params, **kwargs):
        calls.append(params["startdatetime"])
        return Response({"articles": []})

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=0, delay_seconds=0, max_requests_per_run=2,
    )
    end = START + timedelta(days=3)

    collector.collect(START, end)
    assert len(calls) == 2
    collector.collect(START, end)

    assert len(calls) == 3
    assert len(set(calls)) == 3
    assert CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "intelligence"
    )["complete"] is True


def test_reliefweb_historical_collection_paginates_checkpoints_and_uses_created_time(tmp_path):
    calls = []

    def report(record_id, hour):
        return {
            "id": record_id,
            "fields": {
                "title": f"Report {record_id}", "url": f"https://relief.test/{record_id}",
                "date": {"created": f"2026-01-01T{hour:02d}:00:00Z"},
            },
        }

    def get(url, params, **kwargs):
        calls.append(dict(params))
        if params["offset"] == 0:
            return Response({"totalCount": 3, "data": [report("a", 1), report("b", 2)]})
        return Response({"totalCount": 3, "data": [report("c", 3)]})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    collector = ReliefWebHistoricalIntelligenceCollector(
        store, http_get=get, retries=0, delay_seconds=0, page_size=2,
    )

    first = collector.collect(START, START + timedelta(days=1))
    second = collector.collect(START, START + timedelta(days=1))
    records = store.load()

    assert first.added == 3 and second.added == 0
    assert [item["offset"] for item in calls] == [0, 2]
    assert all(item.available_at == item.published_at for item in records)
    assert all(item.metadata["availability_timestamp_policy"] == "reliefweb.date.created"
               for item in records)
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "intelligence_reliefweb"
    )
    assert state["complete"] is True


def test_reliefweb_authorization_failure_stops_without_burning_partitions(tmp_path):
    calls = 0

    def get(url, params, **kwargs):
        nonlocal calls
        calls += 1
        response = requests.Response()
        response.status_code = 403
        return Response(error=requests.HTTPError("not approved", response=response))

    collector = ReliefWebHistoricalIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=0, delay_seconds=0,
    )

    result = collector.collect(START, START + timedelta(days=10))

    assert calls == 1
    assert len(result.failures) == 1
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "intelligence_reliefweb"
    )
    assert len(state["retry_queue"]) == 1
    assert state["complete"] is False


def test_reliefweb_resumes_from_checkpointed_page_offset(tmp_path):
    calls = []
    failed = False

    def report(record_id, hour):
        return {"id": record_id, "fields": {
            "title": record_id, "url": f"https://relief.test/{record_id}",
            "date": {"created": f"2026-01-01T{hour:02d}:00:00Z"},
        }}

    def get(url, params, **kwargs):
        nonlocal failed
        calls.append(params["offset"])
        if params["offset"] == 0:
            return Response({"totalCount": 3, "data": [report("a", 1), report("b", 2)]})
        if not failed:
            failed = True
            return Response(error=requests.Timeout("page retry"))
        return Response({"totalCount": 3, "data": [report("c", 3)]})

    collector = ReliefWebHistoricalIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, retries=0, delay_seconds=0, page_size=2,
    )
    collector.collect(START, START + timedelta(days=1))
    collector.collect(START, START + timedelta(days=1))

    assert calls == [0, 2, 2]
    assert len(collector.store.load()) == 3


def media_cloud_story(story_id="story-1", **changes):
    value = {
        "id": story_id,
        "title": f"Story {story_id}",
        "url": f"https://www.example.test/news/{story_id}?tracking=1",
        "indexed_date": "2026-01-01T12:00:00+00:00",
        "publish_date": "2026-01-01",
        "media_name": "Example", "media_url": "example.test", "language": "en",
    }
    value.update(changes)
    return value


def test_media_cloud_authentication_header_and_structured_403(tmp_path):
    calls = []

    def forbidden(url, params, headers, **kwargs):
        calls.append(headers)
        response = requests.Response()
        response.status_code = 403
        response._content = b'{"message":"invalid token"}'
        return Response(error=requests.HTTPError("forbidden", response=response))

    collector = MediaCloudHistoricalIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=forbidden, api_key="secret", retries=3, delay_seconds=0,
    )

    result = collector.collect(START, START + timedelta(days=2))

    assert len(calls) == 1
    assert calls[0]["Authorization"] == "Token secret"
    assert len(result.failures) == 1
    assert "secret" not in result.failures[0]
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "intelligence_media_cloud"
    )
    assert len(state["retry_queue"]) == 1
    assert state["complete"] is False


def test_media_cloud_authentication_success_and_frozen_manifest_policy(tmp_path):
    seen_headers = []
    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    manifest = HistoricalIntelligenceManifestStore(tmp_path / "manifest.json")
    partitions = manifest.create(START, START + timedelta(days=1), (
        HistoricalIntelligenceProviderSpec(
            "Media Cloud", "Iran", "mediacloud.indexed_date",
        ),
    ))

    def get(url, params, headers, **kwargs):
        seen_headers.append(headers)
        return Response({"stories": [media_cloud_story()], "pagination_token": None})

    result = MediaCloudHistoricalIntelligenceCollector(
        store, http_get=get, api_key="secret", query="Iran",
        retries=0, delay_seconds=0, manifest=manifest,
    ).collect(START, START + timedelta(days=1))

    assert result.failures == () and result.added == 1
    assert seen_headers[0]["Authorization"] == "Token secret"
    assert partitions[0].availability_timestamp_policy == "mediacloud.indexed_date"
    assert manifest.coverage()["Media Cloud"]["complete"] == 1


def test_media_cloud_provenance_passes_pilot_status_validation(tmp_path):
    pilot_path = tmp_path / "pilot.json"
    pilot_path.write_text(json.dumps({
        "status": "planned", "pilot_id": "pilot",
        "summary": {"selected_clusters": 1, "included_markets": 1},
        "clusters": [{
            "cluster_id": "a", "market_ids": ["1"],
            "pre_event_intelligence_start": START.isoformat(),
            "replay_end": (START + timedelta(days=1)).isoformat(),
        }],
    }))
    pilot = load_event_focused_pilot_manifest(pilot_path)
    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    manifest = HistoricalIntelligenceManifestStore(tmp_path / "manifest.json")
    manifest.create(START, START + timedelta(days=1), (
        HistoricalIntelligenceProviderSpec(
            "Media Cloud", "Iran", "mediacloud.indexed_date",
        ),
    ))

    MediaCloudHistoricalIntelligenceCollector(
        store, http_get=lambda *args, **kwargs: Response({
            "stories": [media_cloud_story()], "pagination_token": None,
        }), api_key="secret", query="Iran", retries=0, delay_seconds=0,
        manifest=manifest,
    ).collect(START, START + timedelta(days=1))

    status = pilot_intelligence_status_report(pilot, manifest, store, checkpoint)

    assert status["validation"]["invalid_provenance_records"] == 0
    assert status["validation"]["unsafe_timestamp_records"] == 0
    assert status["ready_for_replay"] is True


def test_media_cloud_429_honors_retry_after_and_retries_once(tmp_path):
    attempts = 0
    sleeps = []

    def get(url, params, headers, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            response = requests.Response()
            response.status_code = 429
            response.headers["Retry-After"] = "75"
            return Response(error=requests.HTTPError("rate limited", response=response))
        return Response({"stories": [media_cloud_story()], "pagination_token": None})

    result = MediaCloudHistoricalIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, api_key="secret", retries=1, delay_seconds=0,
        rate_limit_backoff_seconds=60, sleep=sleeps.append,
        jitter=lambda low, high: low,
    ).collect(START, START + timedelta(days=1))

    assert result.failures == () and attempts == 2
    assert sleeps == pytest.approx([75], abs=.1)


def test_media_cloud_pagination_checkpoint_resumes_at_saved_token(tmp_path):
    calls = []
    fail_second_page = True

    def get(url, params, headers, **kwargs):
        nonlocal fail_second_page
        calls.append(params.get("pagination_token"))
        if params.get("pagination_token") is None:
            return Response({"stories": [media_cloud_story("one")],
                             "pagination_token": "next-page"})
        if fail_second_page:
            fail_second_page = False
            return Response(error=requests.Timeout("resume later"))
        return Response({"stories": [media_cloud_story("two")],
                         "pagination_token": None})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    collector = MediaCloudHistoricalIntelligenceCollector(
        store, http_get=get, api_key="secret", retries=0, delay_seconds=0,
    )
    end = START + timedelta(days=1)

    collector.collect(START, end)
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "intelligence_media_cloud"
    )
    assert state["pagination_tokens"][state["retry_queue"][0]] == "next-page"
    collector.collect(START, end)

    assert calls == [None, "next-page", "next-page"]
    assert len(store.load()) == 2
    assert CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "intelligence_media_cloud"
    )["complete"] is True


def test_media_cloud_uses_indexed_date_and_excludes_post_window_discovery(tmp_path):
    def get(url, params, headers, **kwargs):
        return Response({"stories": [
            media_cloud_story("safe", publish_date="2025-12-30",
                              indexed_date="2026-01-01T18:00:00+00:00"),
            media_cloud_story("late", indexed_date="2026-01-02T00:00:00+00:00"),
        ], "pagination_token": None})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    result = MediaCloudHistoricalIntelligenceCollector(
        store, http_get=get, api_key="secret", retries=0, delay_seconds=0,
    ).collect(START, START + timedelta(days=1))
    record = store.load()[0]

    assert result.incomplete == 1
    assert record.available_at == "2026-01-01T18:00:00+00:00"
    assert record.published_at == record.available_at
    assert record.metadata["publish_date"] == "2025-12-30"
    assert record.metadata["indexed_date"] == "2026-01-01T18:00:00+00:00"
    assert record.metadata["availability_timestamp_policy"] == "mediacloud.indexed_date"


def test_media_cloud_story_id_dedup_and_normalized_url_provenance(tmp_path):
    shared_url = "https://www.example.test/path/?utm_source=test"

    def get(url, params, headers, **kwargs):
        return Response({"stories": [
            media_cloud_story("one", url=shared_url),
            media_cloud_story("one", url=shared_url),
            media_cloud_story("two", url="https://example.test/path"),
        ], "pagination_token": None})

    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    result = MediaCloudHistoricalIntelligenceCollector(
        store, http_get=get, api_key="secret", query="Iran AND nuclear",
        collection_ids=(9272347,), retries=0, delay_seconds=0,
    ).collect(START, START + timedelta(days=1))
    records = store.load()

    assert result.added == 2 and result.duplicates == 1
    assert {item.record_id for item in records} == {
        "mediacloud:one", "mediacloud:two",
    }
    assert {item.metadata["normalized_url"] for item in records} == {
        "example.test/path",
    }
    assert all(item.metadata["historical_provider"] == "Media Cloud" for item in records)
    assert all(item.metadata["query"] == "Iran AND nuclear" for item in records)
    assert all(item.metadata["collection_ids"] == [9272347] for item in records)
    assert all(item.metadata["collection_partition"] for item in records)
    assert _normalized_story_url(shared_url) == "example.test/path"


def test_media_cloud_paces_paginated_requests_at_two_per_minute(tmp_path):
    sleeps = []
    calls = 0

    def get(url, params, headers, **kwargs):
        nonlocal calls
        calls += 1
        return Response({
            "stories": [media_cloud_story(str(calls))],
            "pagination_token": "next" if calls == 1 else None,
        })

    MediaCloudHistoricalIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=get, api_key="secret", retries=0, delay_seconds=30,
        sleep=sleeps.append, jitter=lambda low, high: low,
    ).collect(START, START + timedelta(days=1))

    assert calls == 2
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(30, abs=.1)


def test_representative_multi_provider_collection_and_status_report(tmp_path):
    start, end = START, START + timedelta(days=2)
    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    manifest = HistoricalIntelligenceManifestStore(tmp_path / "intelligence-manifest.json")
    manifest.create(start, end, (
        HistoricalIntelligenceProviderSpec(
            "GDELT", "geopolitics", "gdelt.seendate_first_observed",
        ),
        HistoricalIntelligenceProviderSpec(
            "ReliefWeb", "", "reliefweb.date.created",
        ),
    ))

    def gdelt_get(url, params, **kwargs):
        seen = params["startdatetime"] + "Z"
        return Response({"articles": [{
            "title": seen, "url": f"https://gdelt.test/{seen}", "seendate": seen,
        }]})

    def reliefweb_get(url, params, **kwargs):
        date = params["filter[value][from]"]
        return Response({"totalCount": 1, "data": [{"id": date, "fields": {
            "title": date, "url": f"https://relief.test/{date}",
            "date": {"created": date},
        }}]})

    collector = MultiProviderHistoricalIntelligenceCollector((
        GDELTIntelligenceCollector(
            store, http_get=gdelt_get, retries=0, delay_seconds=0,
            checkpoint=checkpoint, manifest=manifest,
        ),
        ReliefWebHistoricalIntelligenceCollector(
            store, http_get=reliefweb_get, retries=0, delay_seconds=0,
            checkpoint=checkpoint, manifest=manifest,
        ),
    ), manifest)
    collector.collect(start, end)
    status = historical_intelligence_status_report(manifest, store, checkpoint)

    assert [(item["provider"], item["completed_partitions"], item["records"])
            for item in status["providers"]] == [
        ("GDELT", 2, 2), ("ReliefWeb", 2, 2),
    ]
    assert status["warnings"] == []


def test_intentionally_excluded_provider_is_not_collected(tmp_path):
    start, end = START, START + timedelta(days=1)
    store = HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json")
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    manifest = HistoricalIntelligenceManifestStore(tmp_path / "manifest.json")
    manifest.create(start, end, (
        HistoricalIntelligenceProviderSpec("GDELT", "query", "gdelt.seendate"),
        HistoricalIntelligenceProviderSpec("ReliefWeb", "", "reliefweb.date.created"),
    ), alignment={"universe_sha256": "frozen"})
    changed = manifest.exclude_provider("ReliefWeb", "HTTP 403; approval required")
    calls = []

    class Collector:
        def __init__(self, provider):
            self.provider = provider
            self.store = store
            self.checkpoint = checkpoint
            self.window = timedelta(days=1)

        def collect(self, start, end):
            calls.append(self.provider)
            return CollectionResult(0, 0, 0, 0, ())

    MultiProviderHistoricalIntelligenceCollector((
        Collector("GDELT"), Collector("ReliefWeb"),
    ), manifest).collect(start, end)

    assert changed == 1
    assert calls == ["GDELT"]
    assert manifest.provider_exclusion("ReliefWeb")["reason"] == (
        "HTTP 403; approval required"
    )


def test_raw_summary_backfills_categories_and_reports_missing_months(tmp_path):
    market_store = HistoricalMarketDatasetStore(tmp_path / "markets.json")
    record = HistoricalMarketRecord(
        market_id="leadership", condition_id=None,
        question="Will Xi Jinping leave office?",
        created_at="2026-01-01T00:00:00+00:00",
        closed_at="2026-02-01T00:00:00+00:00",
        outcomes=("Yes", "No"), token_ids={"YES": YES_TOKEN, "NO": NO_TOKEN},
        resolution_outcome="Yes", category="OTHER",
        price_history={
            "YES": (PriceCandle("2026-01-15T00:00:00+00:00", .4),),
            "NO": (PriceCandle("2026-01-15T00:00:00+00:00", .6),),
        },
    )
    market_store.save([record])
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    checkpoint.update(
        "markets", discovered_market_denominator=1, discovery_complete=True,
        failed_markets=0, failures=[],
    )
    checkpoint.update("intelligence", completed_windows=[], failures=[])
    builder = HistoricalDatasetBuilder(
        HistoricalMarketCollector(market_store, http_get=market_get([]), checkpoint=checkpoint),
        GDELTIntelligenceCollector(
            HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
            http_get=lambda *args, **kwargs: Response({"articles": []}),
            checkpoint=checkpoint, delay_seconds=0,
        ),
        tmp_path / "summary.json",
    )

    summary = builder.generate_summary(START, END)

    assert market_store.load()[0].category == "LEADERSHIP"
    assert summary.discovered_market_denominator == 1
    assert summary.market_coverage_percentage == 100.0
    assert "2026-03" in summary.validation.market_months_missing
    assert summary.validation.resolved_markets == 1


def test_replay_adapter_excludes_post_resolution_candles_and_preserves_availability():
    market_record = HistoricalMarketRecord(
        market_id="m", condition_id=None, question="Will it happen?",
        created_at=START.isoformat(), closed_at=(START + timedelta(days=2)).isoformat(),
        outcomes=("Yes", "No"), token_ids={"YES": YES_TOKEN, "NO": NO_TOKEN},
        resolution_outcome="Yes", category="POLITICAL",
        price_history={
            "YES": (
                PriceCandle((START + timedelta(days=1)).isoformat(), .4),
                PriceCandle((START + timedelta(days=3)).isoformat(), 1.0),
            ),
            "NO": (PriceCandle((START + timedelta(days=1)).isoformat(), .6),),
        },
    )
    item = HistoricalIntelligenceItem(
        "id", "Event", "GDELT", "https://example.test",
        START.isoformat(), (START + timedelta(hours=1)).isoformat(),
    )

    converted = HistoricalDatasetReplayAdapter().convert([market_record], [item])

    assert len(converted.snapshots) == 1
    assert converted.snapshots[0].resolved_at == (START + timedelta(days=2)).isoformat()
    assert converted.snapshots[0].resolved_yes is True
    assert converted.intelligence[0].available_at == item.available_at
    assert converted.replay_engine().intelligence[0].title == "Event"


def test_replay_adapter_distinguishes_non_yes_no_contracts_from_missing_history():
    market_record = HistoricalMarketRecord(
        market_id="m", condition_id=None, question="How high?",
        created_at=START.isoformat(), closed_at=(START + timedelta(days=2)).isoformat(),
        outcomes=("Over", "Under"), token_ids={"OVER": YES_TOKEN, "UNDER": NO_TOKEN},
        resolution_outcome="Over", price_history={
            "OVER": (PriceCandle((START + timedelta(days=1)).isoformat(), .4),),
            "UNDER": (PriceCandle((START + timedelta(days=1)).isoformat(), .6),),
        },
    )

    converted = HistoricalDatasetReplayAdapter().convert([market_record], [])

    assert converted.skipped_markets == 1
    assert converted.market_exclusions == {"m": "non_binary_yes_no_contract"}


@pytest.mark.parametrize(("body", "status", "metadata", "reason"), [
    ("Invalid token id", 400, {}, "invalid_token"),
    ("market expired", 400, {}, "expired_market"),
    ("request failed", 400, {"umaResolutionStatus": "cancelled"}, "cancelled_market"),
    ("market not found", 404, {}, "unavailable_history"),
    ("invalid filters: startTs and endTs interval is too long", 400, {}, "invalid_timestamps"),
    ("upstream unavailable", 503, {}, "api_network_failure"),
])
def test_clob_failure_classification_is_evidence_based(body, status, metadata, reason):
    exclusion = _classify_clob_failure(
        metadata, "m", "YES", YES_TOKEN,
        PublicDataRequestError("failed", status, body),
    )

    assert exclusion.reason == reason
    assert exclusion.status_code == status


def test_long_price_histories_are_chunked_and_exclusions_are_persisted(tmp_path):
    calls = []

    def get(url, params, **kwargs):
        if "gamma-api" in url:
            return Response([market()])
        calls.append(dict(params))
        return Response({"history": [{"t": params["startTs"], "p": .5}]})

    collector = HistoricalMarketCollector(
        HistoricalMarketDatasetStore(tmp_path / "markets.json"),
        http_get=get, retries=0, delay_seconds=0,
        history_window=timedelta(days=7), workers=1,
    )
    result = collector.collect(START, END)
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("markets")

    assert result.collected == 1
    assert len(calls) > 2
    assert all(call["endTs"] - call["startTs"] <= 7 * 86400 for call in calls)
    assert state["market_exclusions"] == []

    def empty_get(url, params, **kwargs):
        return Response([market(id="empty")]) if "gamma-api" in url else Response({"history": []})

    HistoricalMarketCollector(
        HistoricalMarketDatasetStore(tmp_path / "empty-markets.json"),
        http_get=empty_get, retries=0, delay_seconds=0, workers=1,
    ).collect(START, END)
    exclusion = CollectionCheckpoint(tmp_path / "checkpoint.json").section(
        "markets"
    )["market_exclusions"][0]
    assert exclusion["reason"] == "unavailable_history"


def test_summary_reports_actual_close_creation_and_exclusion_distribution(tmp_path):
    store = HistoricalMarketDatasetStore(tmp_path / "markets.json")
    store.save([HistoricalMarketRecord(
        market_id="m", condition_id=None, question="Question?",
        created_at="2026-01-15T00:00:00+00:00",
        closed_at="2026-02-15T00:00:00+00:00",
        scheduled_end_at="2026-03-01T00:00:00+00:00",
        outcomes=("Yes", "No"), token_ids={"YES": YES_TOKEN, "NO": NO_TOKEN},
        resolution_outcome="Yes",
        price_history={
            "YES": (PriceCandle("2026-02-01T00:00:00+00:00", .5),),
            "NO": (PriceCandle("2026-02-01T00:00:00+00:00", .5),),
        },
    )])
    checkpoint = CollectionCheckpoint(tmp_path / "checkpoint.json")
    checkpoint.update("markets", discovery_complete=True, failed_markets=1, failures=[],
                      market_exclusions=[{"market_id": "bad", "reason": "invalid_token"}])
    checkpoint.update("intelligence", completed_windows=[], failures=[])
    builder = HistoricalDatasetBuilder(
        HistoricalMarketCollector(store, http_get=market_get([]), checkpoint=checkpoint),
        GDELTIntelligenceCollector(
            HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
            http_get=lambda *args, **kwargs: Response({"articles": []}),
            checkpoint=checkpoint, delay_seconds=0,
        ), tmp_path / "summary.json",
    )

    summary = builder.generate_summary(START, END)

    assert summary.markets_by_actual_close_month == {"2026-02": 1}
    assert summary.markets_by_creation_month == {"2026-01": 1}
    assert summary.markets_excluded_by_reason == {"invalid_token": 1}
    assert summary.validation.requested_period_covered is False
    assert "2026-03" in summary.validation.actual_close_months_missing


def test_gdelt_progress_exposes_retry_queue_and_interruption_state(tmp_path):
    progress = []

    def interrupt(url, params, **kwargs):
        raise KeyboardInterrupt

    collector = GDELTIntelligenceCollector(
        HistoricalIntelligenceDatasetStore(tmp_path / "intelligence.json"),
        http_get=interrupt, retries=0, delay_seconds=0, progress=progress.append,
    )
    with pytest.raises(KeyboardInterrupt):
        collector.collect(START, START + timedelta(days=2))
    state = CollectionCheckpoint(tmp_path / "checkpoint.json").section("intelligence")
    assert len(state["retry_queue"]) == 1
    assert state["current_window"] == state["retry_queue"][0]

    collector.http_get = lambda *args, **kwargs: Response({"articles": []})
    collector.reader.http_get = collector.http_get
    collector.collect(START, START + timedelta(days=2))
    assert progress[-1]["retry_queue_size"] == 0
    assert progress[-1]["remaining_windows"] == 0
    assert progress[-1]["resumed_windows"] == 1
    assert progress[-1]["cooldown"]["active"] is False
    assert progress[-1]["estimated_remaining_work"][
        "logical_requests_lower_bound"
    ] == 0


def test_legacy_oversized_clob_failure_is_migrated_to_structured_exclusion():
    exclusions = _legacy_market_exclusions([
        "market 42: 400 Client Error: bad?market=token&startTs=100&endTs=700000&fidelity=60",
    ], [])

    assert exclusions[0]["market_id"] == "42"
    assert exclusions[0]["reason"] == "invalid_timestamps"


@pytest.mark.parametrize("question", [
    "Will the Edmonton Oilers win their next game?",
    "Will Leviatan win the esports match at the port event?",
    "Will the movie Nuclear Invasion win an Oscar?",
    "Will Donald Trump say nuclear in his speech?",
    "Will Toulouse win Coupe de France?",
    'Will Trump post "Ceasefire" on Truth Social this week?',
])
def test_strict_geopolitical_filter_rejects_known_false_positives(question):
    category, reason = _strict_geopolitical_category({"question": question})

    assert category is None
    assert reason in {
        "sports_market", "entertainment_market", "generic_actor_mention",
        "no_known_geopolitical_entity",
    }


def test_strict_geopolitical_filter_requires_entity_and_event_structure():
    category, reason = _strict_geopolitical_category({
        "question": "Will Russia invade Ukraine before July?",
    })

    assert category == "INVASION"
    assert reason == "selected"
    assert _strict_geopolitical_category({
        "question": "Will there be an invasion before July?",
    })[1] == "no_known_geopolitical_entity"
    assert _strict_geopolitical_category({
        "question": "Will the US halt offensive operations in Iran?",
    }) == ("INVASION", "selected")
    assert _strict_geopolitical_category({
        "question": "Will the Houthis successfully target shipping by August?",
    }) == ("SHIPPING", "selected")


@pytest.mark.parametrize(("question", "category"), [
    ("Khamenei out as Supreme Leader of Iran by June 30?", "LEADERSHIP"),
    ("US forcibly removes Khamenei from power by March 31?", "LEADERSHIP"),
    ("US and Iran sign an agreement by June 30?", "DIPLOMATIC"),
    ("Will Trump physically sign US x Iran deal?", "DIPLOMATIC"),
    ("Will the United States blockade of the Strait of Hormuz be lifted?", "POLITICAL"),
])
def test_strict_filter_accepts_targeted_transition_and_agreement_markets(question, category):
    assert _strict_geopolitical_category({"question": question}) == (category, "selected")


def test_metadata_selector_filters_actual_close_and_reports_months(tmp_path):
    rows = [
        market(id="feb", question="Will Russia invade Ukraine?",
               closedTime="2026-02-15T00:00:00Z", endDate="2026-08-01T00:00:00Z"),
        market(id="mar", question="Will Iran face new sanctions?",
               closedTime="2026-03-20T00:00:00Z", endDate="2026-08-01T00:00:00Z"),
        market(id="sports", question="Will the Edmonton Oilers win the NHL game?",
               closedTime="2026-03-21T00:00:00Z", endDate="2026-08-01T00:00:00Z"),
        market(id="late", question="Will Russia invade Ukraine?",
               closedTime="2026-08-01T00:00:00Z", endDate="2026-08-01T00:00:00Z"),
    ]
    store = HistoricalMarketUniverseStore(tmp_path / "selected_markets.json")
    selector = HistoricalMarketSelector(
        store, http_get=lambda *args, **kwargs: Response(rows),
        retries=0, delay_seconds=0,
    )

    selected, report = selector.select(
        datetime(2026, 2, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    assert {item.market_id for item in selected} == {"feb", "mar"}
    assert report.markets_discovered_by_month == {"2026-02": 1, "2026-03": 2}
    assert report.markets_selected_by_month == {"2026-02": 1, "2026-03": 1}
    assert report.excluded_counts_by_reason == {
        "actual_close_out_of_range": 1, "sports_market": 1,
    }
    assert report.geopolitical_category_distribution == {"INVASION": 1, "SANCTIONS": 1}


def test_metadata_selection_persistence_reuses_stable_denominator(tmp_path):
    calls = 0

    def get(*args, **kwargs):
        nonlocal calls
        calls += 1
        return Response([market(
            question="Will China sanction Taiwan?", closedTime="2026-03-01T00:00:00Z",
        )])

    store = HistoricalMarketUniverseStore(tmp_path / "selected_markets.json")
    selector = HistoricalMarketSelector(store, http_get=get, retries=0, delay_seconds=0)
    selector.select(START, END)
    records, report = selector.select(START, END)
    payload = json.loads(store.path.read_text(encoding="utf-8"))

    assert calls == 1
    assert len(records) == report.selected_market_denominator == 1
    assert payload["selection_report"]["discovered_market_denominator"] == 1
    assert payload["excluded_markets"] == []


def test_event_clustering_reports_independence_and_sparse_months(tmp_path):
    def metadata(market_id, question, month, category="DIPLOMATIC"):
        return HistoricalMarketMetadata(
            market_id=market_id, condition_id=None, question=question,
            created_at="2026-01-01T00:00:00+00:00", scheduled_end_at=None,
            actual_close_at=f"{month}-15T00:00:00+00:00", resolution_status="resolved",
            category=category, outcomes=("Yes", "No"),
            token_ids=(YES_TOKEN, NO_TOKEN), outcome_prices=("1", "0"),
        )

    markets = [
        metadata("oman", "Will the next diplomatic US-Iran meeting be in Oman?", "2026-02"),
        metadata("qatar", "Will the next diplomatic US-Iran meeting be in Qatar?", "2026-02"),
        metadata("cuba", "Will the next diplomatic US-Cuba meeting be in Qatar?", "2026-02"),
        metadata("peace", "Will Russia and Ukraine agree to a ceasefire?", "2026-03"),
    ]
    report = analyze_market_universe(
        markets, ("2026-02", "2026-03", "2026-04"), sparse_threshold=2,
    )

    assert report.total_markets == 4
    assert report.unique_event_clusters == 3
    assert report.cluster_size_distribution == {"1": 2, "2": 1}
    assert report.largest_clusters[0].market_count == 2
    assert report.clusters_by_close_month == {"2026-02": 2, "2026-03": 1}
    assert any(warning.startswith("2026-04: 0") for warning in report.sparse_month_warnings)

    store = HistoricalMarketUniverseStore(tmp_path / "selected_markets.json")
    selection = MarketSelectionReport(
        START.isoformat(), END.isoformat(), True, 1, 4, 4, 4,
        {"2026-02": 2, "2026-03": 1}, {"2026-02": 2, "2026-03": 1}, {},
        {"DIPLOMATIC": 4}, "test",
    )
    store.save_selection(markets, selection, [])
    store.save_quality_report(report)
    assert json.loads(store.path.read_text(encoding="utf-8"))["quality_report"][
        "unique_event_clusters"
    ] == 3


def test_collection_manifest_freezes_validates_and_resumes_universe(tmp_path):
    metadata = HistoricalMarketMetadata(
        market_id="frozen", condition_id="condition", question="Will Russia invade Ukraine?",
        created_at="2026-01-01T00:00:00+00:00", scheduled_end_at=None,
        actual_close_at="2026-03-01T00:00:00+00:00", resolution_status="resolved",
        category="INVASION", outcomes=("Yes", "No"),
        token_ids=(YES_TOKEN, NO_TOKEN), outcome_prices=("1", "0"),
    )
    universe = HistoricalMarketUniverseStore(tmp_path / "selected_markets.json")
    selection = MarketSelectionReport(
        START.isoformat(), END.isoformat(), False, 1, 1, 1, 1,
        {"2026-03": 1}, {"2026-03": 1}, {}, {"INVASION": 1}, "4",
    )
    universe.save_selection([metadata], selection, [])
    quality = analyze_market_universe([metadata], ("2026-03",))
    universe.save_quality_report(quality)
    manifests = CollectionManifestStore(tmp_path / "collection_manifest.json")

    manifest = manifests.create(universe, START, END)
    assert manifests.create(universe, START, END) == manifest
    assert manifest.contract_count == 1
    assert manifest.cluster_count == 1
    assert manifest.market_ids == ("frozen",)

    market_store = HistoricalMarketDatasetStore(tmp_path / "markets.json")
    market_store.save([HistoricalMarketRecord(
        market_id="frozen", condition_id="condition", question=metadata.question,
        created_at=metadata.created_at, closed_at=metadata.actual_close_at,
        outcomes=("Yes", "No"), token_ids={"YES": YES_TOKEN, "NO": NO_TOKEN},
        resolution_outcome="Yes", category="INVASION",
        price_history={
            "YES": (PriceCandle("2026-02-01T00:00:00+00:00", .6),),
            "NO": (PriceCandle("2026-02-01T00:00:00+00:00", .4),),
        },
    )])
    collector = HistoricalMarketCollector(
        market_store, http_get=lambda *args, **kwargs: pytest.fail("network called"),
        manifest=manifests, universe=universe,
    )
    resumed = collector.collect(START, END)
    assert resumed.duplicates == 1
    assert resumed.added == 0

    payload = json.loads(universe.path.read_text(encoding="utf-8"))
    payload["records"][0]["question"] = "changed"
    universe.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="metadata changed"):
        manifests.validate(universe)

    payload["records"][0]["question"] = metadata.question
    payload["records"][0]["market_id"] = "replacement"
    universe.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="selected markets changed"):
        manifests.validate(universe)

    payload["records"][0]["market_id"] = metadata.market_id
    payload["records"].append(dict(payload["records"][0]))
    universe.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate market IDs"):
        manifests.validate(universe)
