# File-Version: 1.1.0
"""Read-only collectors for reproducible historical backtest datasets."""

from __future__ import annotations

import argparse
import atexit
import collections
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import threading
import time
from typing import Any, Callable, Generic, TypeVar
from urllib.parse import urlsplit

import requests

from src.config import (
    INTELLIGENCE_USER_AGENT, MEDIA_CLOUD_API_KEY, MEDIA_CLOUD_API_URL,
    MEDIA_CLOUD_COLLECTION_IDS, RELIEFWEB_API_URL, RELIEFWEB_APPNAME, REQUEST_TIMEOUT,
)
from src.coverage_probe import (
    CLOB_HISTORY_URL,
    GAMMA_MARKETS_URL,
    GDELT_DOC_URL,
    HistoricalCoverageProbe,
    _iso,
    _items,
    _timestamp,
)
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.classification import EventType
from src.intelligence.knowledge import ACTORS, COUNTRIES
from src.paper_trading.historical import (
    HistoricalIntelligenceRecord,
    HistoricalMarketSnapshot,
    HistoricalReplayEngine,
)


HttpGet = Callable[..., Any]
T = TypeVar("T")
ProgressCallback = Callable[[dict[str, Any]], None]
GAMMA_KEYSET_MARKETS_URL = f"{GAMMA_MARKETS_URL}/keyset"
GDELT_ARTICLE_RESULT_LIMIT = 250
GDELT_MINIMUM_PARTITION = timedelta(minutes=15)
GDELT_LOGICAL_REQUEST_BUDGET = 25
GDELT_REQUEST_DELAY_MIN_SECONDS = 30.0
GDELT_REQUEST_DELAY_MAX_SECONDS = 45.0
GDELT_COOLDOWN_MIN_SECONDS = 60.0
GDELT_COOLDOWN_MAX_SECONDS = 120.0


@dataclass(frozen=True)
class PriceCandle:
    timestamp: str
    price: float

    def __post_init__(self) -> None:
        if _timestamp(self.timestamp) is None:
            raise ValueError("invalid candle timestamp")
        if not 0.0 <= self.price <= 1.0:
            raise ValueError("price must be between zero and one")


@dataclass(frozen=True)
class HistoricalMarketRecord:
    market_id: str
    condition_id: str | None
    question: str
    created_at: str
    closed_at: str
    outcomes: tuple[str, ...]
    token_ids: dict[str, str]
    resolution_outcome: str | None
    price_history: dict[str, tuple[PriceCandle, ...]]
    volume: float | None = None
    liquidity: float | None = None
    category: str = "OTHER"
    scheduled_end_at: str | None = None

    def __post_init__(self) -> None:
        if not self.market_id or not self.question or len(self.outcomes) < 2:
            raise ValueError("incomplete historical market")
        if _timestamp(self.created_at) is None or _timestamp(self.closed_at) is None:
            raise ValueError("invalid market timestamps")
        if self.scheduled_end_at is not None and _timestamp(self.scheduled_end_at) is None:
            raise ValueError("invalid scheduled market end timestamp")

    @property
    def has_valid_price_history(self) -> bool:
        return len(self.token_ids) >= 2 and all(
            bool(self.price_history.get(outcome.upper())) for outcome in self.outcomes
        )


@dataclass(frozen=True)
class HistoricalIntelligenceItem:
    record_id: str
    title: str
    source: str
    source_url: str
    published_at: str
    available_at: str
    source_domain: str | None = None
    source_country: str | None = None
    language: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.record_id or not self.title:
            raise ValueError("incomplete intelligence record")
        if _timestamp(self.published_at) is None or _timestamp(self.available_at) is None:
            raise ValueError("invalid intelligence timestamps")


@dataclass(frozen=True)
class HistoricalMarketMetadata:
    """Gamma metadata retained before any CLOB history is requested."""

    market_id: str
    condition_id: str | None
    question: str
    created_at: str
    scheduled_end_at: str | None
    actual_close_at: str
    resolution_status: str
    category: str
    outcomes: tuple[str, ...]
    token_ids: tuple[str, ...]
    outcome_prices: tuple[str, ...]
    volume: float | None = None
    liquidity: float | None = None

    def __post_init__(self) -> None:
        if not self.market_id or not self.question:
            raise ValueError("incomplete market metadata")
        if _timestamp(self.created_at) is None or _timestamp(self.actual_close_at) is None:
            raise ValueError("invalid market metadata timestamps")

    def as_gamma_market(self) -> dict[str, Any]:
        return {
            "id": self.market_id, "conditionId": self.condition_id,
            "question": self.question, "createdAt": self.created_at,
            "endDate": self.scheduled_end_at, "closedTime": self.actual_close_at,
            "outcomes": list(self.outcomes), "clobTokenIds": list(self.token_ids),
            "outcomePrices": list(self.outcome_prices), "volume": self.volume,
            "liquidity": self.liquidity, "category": self.category,
            "resolutionStatus": self.resolution_status,
        }


@dataclass(frozen=True)
class MarketSelectionReport:
    start: str
    end: str
    discovery_complete: bool
    pages_scanned: int
    markets_scanned: int
    discovered_market_denominator: int
    selected_market_denominator: int
    markets_discovered_by_month: dict[str, int]
    markets_selected_by_month: dict[str, int]
    excluded_counts_by_reason: dict[str, int]
    geopolitical_category_distribution: dict[str, int]
    selector_version: str = "legacy"


@dataclass(frozen=True)
class EventCluster:
    cluster_id: str
    label: str
    category: str
    market_count: int
    market_ids: tuple[str, ...]
    actual_close_months: tuple[str, ...]


@dataclass(frozen=True)
class MarketUniverseQualityReport:
    generated_at: str
    total_markets: int
    unique_event_clusters: int
    singleton_clusters: int
    effective_independence_percentage: float
    selected_markets_by_month: dict[str, int]
    category_distribution: dict[str, int]
    cluster_size_distribution: dict[str, int]
    clusters_by_close_month: dict[str, int]
    sparse_month_warnings: tuple[str, ...]
    largest_clusters: tuple[EventCluster, ...]


class VersionedJsonStore(Generic[T]):
    """Atomic, migration-friendly JSON record storage."""

    version = 1

    def __init__(
        self,
        path: str | Path,
        decoder: Callable[[dict[str, Any]], T],
        identity: Callable[[T], str],
    ) -> None:
        self.path = Path(path)
        self.decoder = decoder
        self.identity = identity
        self.invalid_records = 0

    def load(self) -> list[T]:
        self.invalid_records = 0
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.invalid_records = 1
            return []
        raw = payload.get("records", []) if isinstance(payload, dict) else []
        if not isinstance(raw, list):
            self.invalid_records = 1
            return []
        records: list[T] = []
        for item in raw:
            try:
                records.append(self.decoder(item))
            except (TypeError, ValueError, AttributeError):
                self.invalid_records += 1
        return records

    def save(self, records: list[T]) -> None:
        unique = {self.identity(record): record for record in records}
        _atomic_json(self.path, {
            "version": self.version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "records": [asdict(unique[key]) for key in sorted(unique)],
        })

    def upsert(self, records: list[T]) -> tuple[int, int]:
        existing = {self.identity(record): record for record in self.load()}
        incoming = {self.identity(record): record for record in records}
        added = sum(key not in existing for key in incoming)
        duplicates = len(records) - added
        existing.update(incoming)
        self.save(list(existing.values()))
        return added, duplicates


def _market_decoder(value: dict[str, Any]) -> HistoricalMarketRecord:
    histories = {
        outcome: tuple(PriceCandle(**candle) for candle in candles)
        for outcome, candles in value.get("price_history", {}).items()
    }
    return HistoricalMarketRecord(
        market_id=value["market_id"], condition_id=value.get("condition_id"),
        question=value["question"], created_at=value["created_at"],
        closed_at=value["closed_at"], outcomes=tuple(value["outcomes"]),
        token_ids=dict(value["token_ids"]),
        resolution_outcome=value.get("resolution_outcome"),
        price_history=histories, volume=value.get("volume"),
        liquidity=value.get("liquidity"), category=value.get("category", "OTHER"),
        scheduled_end_at=value.get("scheduled_end_at"),
    )


def _intelligence_decoder(value: dict[str, Any]) -> HistoricalIntelligenceItem:
    return HistoricalIntelligenceItem(**value)


class HistoricalMarketDatasetStore(VersionedJsonStore[HistoricalMarketRecord]):
    def __init__(self, path: str | Path) -> None:
        super().__init__(path, _market_decoder, lambda item: item.market_id)

    def classify_existing(self) -> int:
        """Backfill deterministic categories without recollecting market histories."""
        records = self.load()
        updated = [
            replace(record, category=_market_category({"question": record.question}))
            if record.category == "OTHER" else record
            for record in records
        ]
        changed = sum(left.category != right.category for left, right in zip(records, updated))
        if changed:
            self.save(updated)
        return changed


class HistoricalIntelligenceDatasetStore(VersionedJsonStore[HistoricalIntelligenceItem]):
    def __init__(self, path: str | Path) -> None:
        super().__init__(path, _intelligence_decoder, lambda item: item.record_id)


@dataclass(frozen=True)
class HistoricalIntelligenceProviderSpec:
    provider: str
    query: str
    availability_timestamp_policy: str


@dataclass(frozen=True)
class HistoricalIntelligencePartition:
    partition_id: str
    provider: str
    query: str
    start: str
    end: str
    availability_timestamp_policy: str


class HistoricalIntelligenceManifestStore:
    """Frozen provider/query/day plan with separately mutable collection status."""

    version = 1
    valid_statuses = {"pending", "collecting", "split", "complete", "failed", "saturated"}

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _partition_id(provider: str, start: datetime, end: datetime) -> str:
        return f"{provider.lower()}:{start.isoformat()}..{end.isoformat()}"

    @staticmethod
    def _digest(partitions: list[HistoricalIntelligencePartition]) -> str:
        encoded = json.dumps(
            [asdict(item) for item in partitions], sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def create(
        self, start: datetime, end: datetime,
        providers: tuple[HistoricalIntelligenceProviderSpec, ...],
        window: timedelta = timedelta(days=1),
    ) -> list[HistoricalIntelligencePartition]:
        start, end = _utc_range(start, end)
        if window.total_seconds() <= 0 or not providers:
            raise ValueError("intelligence manifest needs providers and a positive window")
        partitions: list[HistoricalIntelligencePartition] = []
        for provider in providers:
            cursor = start
            while cursor < end:
                partition_end = min(cursor + window, end)
                partitions.append(HistoricalIntelligencePartition(
                    self._partition_id(provider.provider, cursor, partition_end),
                    provider.provider, provider.query, cursor.isoformat(),
                    partition_end.isoformat(), provider.availability_timestamp_policy,
                ))
                cursor = partition_end
        partitions.sort(key=lambda item: (item.provider, item.start, item.end))
        digest = self._digest(partitions)
        if self.path.exists():
            existing = self.load_partitions()
            if self._digest(existing) != digest:
                raise ValueError("historical intelligence manifest already freezes a different plan")
            return existing
        _atomic_json(self.path, {
            "manifest_version": self.version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "evaluation_start": start.isoformat(), "evaluation_end": end.isoformat(),
            "partition_seconds": int(window.total_seconds()),
            "providers": [asdict(item) for item in providers],
            "partitions": [asdict(item) for item in partitions],
            "plan_sha256": digest,
            "collection_status": {
                item.partition_id: {"status": "pending"} for item in partitions
            },
        })
        return partitions

    def load_partitions(self, provider: str | None = None) -> list[HistoricalIntelligencePartition]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("manifest_version") != self.version:
                raise ValueError("unsupported historical intelligence manifest version")
            records = [HistoricalIntelligencePartition(**item) for item in payload["partitions"]]
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError("historical intelligence manifest is missing or invalid") from error
        if self._digest(records) != payload.get("plan_sha256"):
            raise ValueError("historical intelligence manifest plan changed after freezing")
        return [item for item in records if provider is None or item.provider == provider]

    def update_status(self, partition_id: str, status: str, **details: Any) -> None:
        if status not in self.valid_statuses:
            raise ValueError("invalid historical intelligence collection status")
        self.load_partitions()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        ids = {item["partition_id"] for item in payload.get("partitions", [])}
        if partition_id not in ids:
            raise ValueError("partition is not frozen in the intelligence manifest")
        current = payload.setdefault("collection_status", {}).get(partition_id, {})
        current.update({"status": status, "updated_at": datetime.now(timezone.utc).isoformat()})
        current.update(details)
        payload["collection_status"][partition_id] = current
        _atomic_json(self.path, payload)

    def coverage(self) -> dict[str, dict[str, int]]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        statuses = payload.get("collection_status", {})
        result: dict[str, dict[str, int]] = {}
        for partition in self.load_partitions():
            provider = result.setdefault(
                partition.provider, {"total": 0, "complete": 0, "failed": 0, "pending": 0},
            )
            provider["total"] += 1
            status = statuses.get(partition.partition_id, {}).get("status", "pending")
            if status == "complete":
                provider["complete"] += 1
            elif status in {"failed", "saturated"}:
                provider["failed"] += 1
            else:
                provider["pending"] += 1
        return result

    def coverage_days(self) -> dict[str, dict[str, str]]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        statuses = payload.get("collection_status", {})
        result: dict[str, dict[str, str]] = {}
        for partition in self.load_partitions():
            result.setdefault(partition.provider, {})[partition.start[:10]] = str(
                statuses.get(partition.partition_id, {}).get("status", "pending")
            )
        return result


def historical_intelligence_status_report(
    manifest: HistoricalIntelligenceManifestStore,
    store: HistoricalIntelligenceDatasetStore,
    checkpoint: CollectionCheckpoint,
) -> dict[str, Any]:
    """Return an operator-facing, read-only provider/partition coverage report."""
    manifest.load_partitions()
    payload = json.loads(manifest.path.read_text(encoding="utf-8"))
    statuses = payload.get("collection_status", {})
    records: dict[str, int] = {}
    for item in store.load():
        provider = str(item.metadata.get("historical_provider") or item.source)
        records[provider] = records.get(provider, 0) + 1
    providers: list[dict[str, Any]] = []
    warnings: list[str] = []
    for provider in sorted({item.provider for item in manifest.load_partitions()}):
        partitions = manifest.load_partitions(provider)
        provider_statuses = [statuses.get(item.partition_id, {}) for item in partitions]
        completed = sum(item.get("status") == "complete" for item in provider_statuses)
        failed = sum(item.get("status") in {"failed", "saturated"} for item in provider_statuses)
        saturated = sum(item.get("status") == "saturated" for item in provider_statuses)
        legacy_truncated = sum(
            bool(item.get("requires_adaptive_split")) for item in provider_statuses
        )
        if saturated:
            warnings.append(
                f"{provider}: {saturated} minimum-size partitions still hit the result limit"
            )
        if legacy_truncated:
            warnings.append(
                f"{provider}: {legacy_truncated} legacy capped days require adaptive recollection"
            )
        providers.append({
            "provider": provider, "total_partitions": len(partitions),
            "completed_partitions": completed,
            "pending_partitions": len(partitions) - completed - failed,
            "failed_partitions": failed, "records": records.get(provider, 0),
            "saturated_partitions": saturated,
            "legacy_truncated_partitions": legacy_truncated,
        })
    gdelt_state = checkpoint.section("intelligence")
    adaptive = gdelt_state.get("adaptive_partitions", {})
    pending_leaves = sum(
        item.get("status") != "complete"
        for leaves in adaptive.values() if isinstance(leaves, list)
        for item in leaves if isinstance(item, dict)
    ) if isinstance(adaptive, dict) else 0
    current = gdelt_state.get("current_window")
    if current:
        warnings.append(f"GDELT: interrupted partition remains resumable: {current}")
    reliefweb_state = checkpoint.section("intelligence_reliefweb")
    relief_current = reliefweb_state.get("current_window")
    if relief_current:
        warnings.append(f"ReliefWeb: interrupted partition remains resumable: {relief_current}")
    if any("403 Client Error" in str(item) for item in reliefweb_state.get("failures", [])):
        warnings.append(
            "ReliefWeb: authorization is blocked; set an approved RELIEFWEB_APPNAME before resume"
        )
    media_cloud_state = checkpoint.section("intelligence_media_cloud")
    media_cloud_current = media_cloud_state.get("current_window")
    if media_cloud_current:
        warnings.append(
            f"Media Cloud: interrupted partition remains resumable: {media_cloud_current}"
        )
    if any("403 Client Error" in str(item) for item in media_cloud_state.get("failures", [])):
        warnings.append(
            "Media Cloud: authorization failed; verify MEDIA_CLOUD_API_KEY before resume"
        )
    gdelt_coverage = next(
        (item for item in providers if item["provider"] == "GDELT"), None,
    )
    gdelt_remaining = (
        gdelt_coverage["total_partitions"] - gdelt_coverage["completed_partitions"]
        if gdelt_coverage is not None else 0
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": payload.get("plan_sha256"),
        "providers": providers,
        "gdelt_adaptive": {
            "roots_with_leaves": len(adaptive) if isinstance(adaptive, dict) else 0,
            "pending_leaves": pending_leaves,
            "logical_request_budget_per_run": GDELT_LOGICAL_REQUEST_BUDGET,
            "result_limit": GDELT_ARTICLE_RESULT_LIMIT,
            "minimum_partition_minutes": int(GDELT_MINIMUM_PARTITION.total_seconds() / 60),
            "last_checkpoint_cooldown": gdelt_state.get("cooldown", {
                "active": False, "remaining_seconds": 0, "reason": None,
                "rate_limit_events": 0,
            }),
            "rate_limit_events_last_run": int(
                gdelt_state.get("rate_limit_events_this_run", 0)
            ),
            "persistent_rate_limit_failures_last_run": int(
                gdelt_state.get("persistent_rate_limit_failures_this_run", 0)
            ),
            "rate_limit_pause_triggered": bool(
                gdelt_state.get("rate_limit_pause_triggered", False)
            ),
            "estimated_remaining_work": {
                "windows": gdelt_remaining,
                "logical_requests_lower_bound": max(gdelt_remaining, pending_leaves),
                "minutes_at_normal_pacing": round(
                    max(gdelt_remaining, pending_leaves)
                    * (GDELT_REQUEST_DELAY_MIN_SECONDS + GDELT_REQUEST_DELAY_MAX_SECONDS)
                    / 2 / 60, 1,
                ),
            },
        },
        "warnings": warnings,
    }


def load_event_focused_pilot_manifest(path: str | Path) -> dict[str, Any]:
    """Validate the frozen event-focused pilot plan without reading replay outcomes."""
    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
        payload = json.loads(raw)
        clusters = payload["clusters"]
        summary = payload["summary"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError("event-focused pilot manifest is missing or invalid") from error
    if payload.get("status") != "planned" or not isinstance(clusters, list) or not clusters:
        raise ValueError("event-focused pilot manifest is not a frozen collection plan")
    cluster_ids = [str(item.get("cluster_id") or "") for item in clusters]
    market_ids = [
        str(market_id)
        for item in clusters
        for market_id in item.get("market_ids", [])
    ]
    if not all(cluster_ids) or len(cluster_ids) != len(set(cluster_ids)):
        raise ValueError("event-focused pilot manifest has duplicate or missing clusters")
    if not market_ids or len(market_ids) != len(set(market_ids)):
        raise ValueError("event-focused pilot manifest has duplicate or missing markets")
    if int(summary.get("selected_clusters", -1)) != len(cluster_ids):
        raise ValueError("event-focused pilot cluster denominator changed")
    if int(summary.get("included_markets", -1)) != len(market_ids):
        raise ValueError("event-focused pilot market denominator changed")
    starts = [_timestamp(item.get("pre_event_intelligence_start")) for item in clusters]
    ends = [_timestamp(item.get("replay_end")) for item in clusters]
    if any(item is None for item in starts + ends):
        raise ValueError("event-focused pilot contains invalid collection timestamps")
    if any(start >= end for start, end in zip(starts, ends)):
        raise ValueError("event-focused pilot contains an empty collection window")
    payload["_manifest_path"] = str(manifest_path.resolve())
    payload["_manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    payload["_collection_start"] = min(starts).isoformat()
    payload["_collection_end"] = max(ends).isoformat()
    return payload


def freeze_pilot_collection_reference(
    pilot: dict[str, Any], output_path: str | Path,
) -> None:
    """Persist the immutable pilot identity beside its separately collected data."""
    clusters = pilot["clusters"]
    expected = {
        "version": 1,
        "pilot_id": pilot.get("pilot_id"),
        "source_manifest_path": pilot["_manifest_path"],
        "source_manifest_sha256": pilot["_manifest_sha256"],
        "source_universe": pilot.get("source_universe", {}),
        "collection_start": pilot["_collection_start"],
        "collection_end": pilot["_collection_end"],
        "cluster_ids": [item["cluster_id"] for item in clusters],
        "market_ids": [market_id for item in clusters for market_id in item["market_ids"]],
    }
    path = Path(output_path)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("pilot collection reference is invalid") from error
        if existing != expected:
            raise ValueError("pilot output directory freezes a different pilot manifest")
        return
    _atomic_json(path, expected)


def pilot_intelligence_status_report(
    pilot: dict[str, Any], manifest: HistoricalIntelligenceManifestStore,
    store: HistoricalIntelligenceDatasetStore, checkpoint: CollectionCheckpoint,
) -> dict[str, Any]:
    """Audit pilot provider/day coverage, provenance, and timestamp safety."""
    status = historical_intelligence_status_report(manifest, store, checkpoint)
    partitions = manifest.load_partitions()
    manifest_payload = json.loads(manifest.path.read_text(encoding="utf-8"))
    collection_status = manifest_payload.get("collection_status", {})
    missing_days: dict[str, list[str]] = {}
    for provider in sorted({item.provider for item in partitions}):
        missing_days[provider] = [
            item.start[:10] for item in partitions
            if item.provider == provider
            and collection_status.get(item.partition_id, {}).get("status") != "complete"
        ]
    specs = {
        item.provider: item.availability_timestamp_policy for item in partitions
    }
    partition_roots = {
        (item.provider, f"{item.start}..{item.end}") for item in partitions
    }
    invalid_provenance: list[str] = []
    unsafe_timestamps: list[str] = []
    records_by_day: dict[str, dict[str, int]] = {}
    for item in store.load():
        provider = str(item.metadata.get("historical_provider") or item.source)
        published, available = _timestamp(item.published_at), _timestamp(item.available_at)
        partition_start = str(item.metadata.get("partition_start") or "")
        partition_end = str(item.metadata.get("partition_end") or "")
        policy = item.metadata.get("availability_timestamp_policy")
        media_cloud_provenance_invalid = (
            provider == "Media Cloud"
            and (
                not item.metadata.get("media_cloud_story_id")
                or not item.metadata.get("normalized_url")
                or not item.metadata.get("collection_partition")
                or _timestamp(str(item.metadata.get("indexed_date") or ""))
                != available
            )
        )
        if (
            provider not in specs
            or policy != specs.get(provider)
            or (provider, str(item.metadata.get("root_partition") or ""))
            not in partition_roots
            or _timestamp(partition_start) is None
            or _timestamp(partition_end) is None
            or media_cloud_provenance_invalid
        ):
            invalid_provenance.append(item.record_id)
        if published is None or available is None or available < published:
            unsafe_timestamps.append(item.record_id)
        day = item.published_at[:10]
        provider_days = records_by_day.setdefault(provider, {})
        provider_days[day] = provider_days.get(day, 0) + 1
    providers_complete = all(
        item["completed_partitions"] == item["total_partitions"]
        and item["failed_partitions"] == 0
        for item in status["providers"]
    )
    ready = (
        providers_complete and not any(missing_days.values())
        and not invalid_provenance and not unsafe_timestamps
        and not status["warnings"]
    )
    status["pilot"] = {
        "pilot_id": pilot.get("pilot_id"),
        "source_manifest_sha256": pilot["_manifest_sha256"],
        "selected_clusters": len(pilot["clusters"]),
        "included_markets": sum(len(item["market_ids"]) for item in pilot["clusters"]),
        "collection_start": pilot["_collection_start"],
        "collection_end": pilot["_collection_end"],
    }
    status["coverage_by_provider_day"] = manifest.coverage_days()
    status["records_by_provider_day"] = records_by_day
    status["missing_days"] = missing_days
    status["validation"] = {
        "records_checked": sum(
            sum(days.values()) for days in records_by_day.values()
        ),
        "invalid_provenance_records": len(invalid_provenance),
        "unsafe_timestamp_records": len(unsafe_timestamps),
        "availability_timestamp_policies": specs,
    }
    status["ready_for_replay"] = ready
    return status


def _metadata_decoder(value: dict[str, Any]) -> HistoricalMarketMetadata:
    return HistoricalMarketMetadata(
        market_id=value["market_id"], condition_id=value.get("condition_id"),
        question=value["question"], created_at=value["created_at"],
        scheduled_end_at=value.get("scheduled_end_at"),
        actual_close_at=value["actual_close_at"],
        resolution_status=value.get("resolution_status", "unknown"),
        category=value.get("category", "OTHER"), outcomes=tuple(value.get("outcomes", [])),
        token_ids=tuple(value.get("token_ids", [])),
        outcome_prices=tuple(value.get("outcome_prices", [])),
        volume=value.get("volume"), liquidity=value.get("liquidity"),
    )


class HistoricalMarketUniverseStore(VersionedJsonStore[HistoricalMarketMetadata]):
    """Selected metadata denominator plus auditable exclusion decisions."""

    version = 1

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, _metadata_decoder, lambda item: item.market_id)

    def save_selection(
        self, records: list[HistoricalMarketMetadata], report: MarketSelectionReport,
        exclusions: list[dict[str, str]],
    ) -> None:
        unique = {record.market_id: record for record in records}
        _atomic_json(self.path, {
            "version": self.version, "updated_at": datetime.now(timezone.utc).isoformat(),
            "selection_report": asdict(report),
            "records": [asdict(unique[key]) for key in sorted(unique)],
            "excluded_markets": exclusions,
        })

    def report(self) -> MarketSelectionReport | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")).get("selection_report")
            return MarketSelectionReport(**value) if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def save_quality_report(self, report: MarketUniverseQualityReport) -> None:
        if not self.path.exists():
            raise ValueError("selected market universe does not exist")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("selected market universe is invalid") from error
        if not isinstance(payload, dict):
            raise ValueError("selected market universe is invalid")
        payload["quality_report"] = asdict(report)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(self.path, payload)


@dataclass(frozen=True)
class CollectionManifest:
    manifest_version: int
    selector_version: str
    generated_at: str
    evaluation_start: str
    evaluation_end: str
    contract_count: int
    cluster_count: int
    monthly_distribution: dict[str, int]
    category_distribution: dict[str, int]
    market_ids: tuple[str, ...]
    universe_sha256: str


def _universe_digest(records: list[HistoricalMarketMetadata]) -> str:
    canonical = json.dumps(
        [asdict(item) for item in sorted(records, key=lambda item: item.market_id)],
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CollectionManifestStore:
    """Immutable contract between metadata selection and downstream collection."""

    manifest_version = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> CollectionManifest:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            value["market_ids"] = tuple(value["market_ids"])
            return CollectionManifest(**value)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError("collection manifest is missing or invalid") from error

    def create(
        self, universe: HistoricalMarketUniverseStore,
        evaluation_start: datetime, evaluation_end: datetime,
    ) -> CollectionManifest:
        evaluation_start, evaluation_end = _utc_range(evaluation_start, evaluation_end)
        records = universe.load()
        self._reject_duplicates(records)
        if not records:
            raise ValueError("cannot freeze an empty selected universe")
        outside = [
            item.market_id for item in records
            if not evaluation_start <= (_timestamp(item.actual_close_at) or evaluation_end) < evaluation_end
        ]
        if outside:
            raise ValueError("selected universe contains markets outside the evaluation range")
        try:
            payload = json.loads(universe.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("selected market universe is invalid") from error
        selection = payload.get("selection_report", {})
        quality = payload.get("quality_report", {})
        if not isinstance(selection, dict) or not isinstance(quality, dict):
            raise ValueError("selection and quality reports are required before freezing")
        manifest = CollectionManifest(
            manifest_version=self.manifest_version,
            selector_version=str(selection.get("selector_version") or "unknown"),
            generated_at=datetime.now(timezone.utc).isoformat(),
            evaluation_start=evaluation_start.isoformat(),
            evaluation_end=evaluation_end.isoformat(), contract_count=len(records),
            cluster_count=int(quality.get("unique_event_clusters", 0)),
            monthly_distribution=dict(quality.get("selected_markets_by_month", {})),
            category_distribution=dict(quality.get("category_distribution", {})),
            market_ids=tuple(sorted(item.market_id for item in records)),
            universe_sha256=_universe_digest(records),
        )
        if self.path.exists():
            existing = self.load()
            if existing != manifest:
                # Generation time is expected to differ; all frozen content may not.
                if replace(existing, generated_at=manifest.generated_at) != manifest:
                    raise ValueError("collection manifest already freezes a different universe")
            return existing
        _atomic_json(self.path, asdict(manifest))
        return manifest

    def validate(
        self, universe: HistoricalMarketUniverseStore,
    ) -> tuple[CollectionManifest, list[HistoricalMarketMetadata]]:
        manifest = self.load()
        records = universe.load()
        self._reject_duplicates(records)
        ids = tuple(sorted(item.market_id for item in records))
        if len(records) != manifest.contract_count or ids != manifest.market_ids:
            raise ValueError("selected markets changed after the collection manifest was frozen")
        if _universe_digest(records) != manifest.universe_sha256:
            raise ValueError("selected market metadata changed after the manifest was frozen")
        if manifest.manifest_version != self.manifest_version:
            raise ValueError("unsupported collection manifest version")
        return manifest, records

    @staticmethod
    def _reject_duplicates(records: list[HistoricalMarketMetadata]) -> None:
        ids = [item.market_id for item in records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate market IDs are not allowed in a frozen universe")


@dataclass(frozen=True)
class CollectionResult:
    collected: int
    added: int
    duplicates: int
    incomplete: int
    failures: tuple[str, ...]


@dataclass(frozen=True)
class MarketExclusion:
    market_id: str
    reason: str
    detail: str
    outcome: str | None = None
    token_id: str | None = None
    status_code: int | None = None


class PublicDataRequestError(RuntimeError):
    """Request failure retaining machine-readable HTTP diagnostics."""

    def __init__(
        self, detail: str, status_code: int | None = None,
        response_body: str = "",
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.response_body = response_body


class MarketCollectionError(RuntimeError):
    def __init__(self, exclusion: MarketExclusion) -> None:
        super().__init__(exclusion.detail)
        self.exclusion = exclusion


class CollectionCheckpoint:
    """Atomic durable state used to resume an interrupted collection."""

    version = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": self.version, "markets": {}, "intelligence": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": self.version, "markets": {}, "intelligence": {}}
        return value if isinstance(value, dict) else {"version": self.version}

    def section(self, name: str) -> dict[str, Any]:
        value = self.load().get(name, {})
        return value if isinstance(value, dict) else {}

    def update(self, name: str, **changes: Any) -> None:
        state = self.load()
        section = state.get(name, {})
        if not isinstance(section, dict):
            section = {}
        section.update(changes)
        state.update({"version": self.version, "updated_at": _iso(datetime.now(timezone.utc))})
        state[name] = section
        _atomic_json(self.path, state)


class CollectionRunLock:
    """Process-held lock preventing concurrent writers for one output directory."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.handle: Any = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            self.handle.close()
            self.handle = None
            raise RuntimeError("another historical dataset collection is already running") from error

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


@dataclass(frozen=True)
class DatasetValidation:
    duplicate_markets: int = 0
    duplicate_intelligence: int = 0
    markets_with_unordered_candles: int = 0
    markets_with_duplicate_candles: int = 0
    markets_with_missing_periods: int = 0
    incomplete_outcomes: int = 0
    intelligence_windows_expected: int = 0
    intelligence_windows_covered: int = 0
    intelligence_windows_missing: int = 0
    resolved_markets: int = 0
    unresolved_markets: int = 0
    invalid_resolution_outcomes: int = 0
    markets_closed_before_scheduled_end: int = 0
    market_months_covered: tuple[str, ...] = ()
    market_months_missing: tuple[str, ...] = ()
    actual_close_months_covered: tuple[str, ...] = ()
    actual_close_months_missing: tuple[str, ...] = ()
    creation_months_covered: tuple[str, ...] = ()
    requested_period_covered: bool = False


def _emit(callback: ProgressCallback | None, started: float, **values: Any) -> None:
    if callback is not None:
        callback({**values, "elapsed_seconds": round(time.monotonic() - started, 1)})


class RetryingReader:
    """Small retry/rate-limit boundary shared by public collectors."""

    def __init__(
        self, http_get: HttpGet, timeout: float, retries: int,
        delay_seconds: float, sleep: Callable[[float], None],
        rate_limit_backoff_seconds: float = 5.0,
        maximum_delay_seconds: float | None = None,
        maximum_rate_limit_backoff_seconds: float | None = None,
        jitter: Callable[[float, float], float] = random.uniform,
        headers: dict[str, str] | None = None,
        non_retryable_statuses: frozenset[int] = frozenset(),
    ) -> None:
        maximum_delay = delay_seconds if maximum_delay_seconds is None else maximum_delay_seconds
        maximum_backoff = (
            rate_limit_backoff_seconds if maximum_rate_limit_backoff_seconds is None
            else maximum_rate_limit_backoff_seconds
        )
        if (
            retries < 0 or delay_seconds < 0 or rate_limit_backoff_seconds < 0
            or maximum_delay < delay_seconds
            or maximum_backoff < rate_limit_backoff_seconds
        ):
            raise ValueError("retry and delay settings cannot be negative")
        self.http_get = http_get
        self.timeout = timeout
        self.retries = retries
        self.delay_seconds = delay_seconds
        self.maximum_delay_seconds = maximum_delay
        self.rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self.maximum_rate_limit_backoff_seconds = maximum_backoff
        self.jitter = jitter
        self.non_retryable_statuses = non_retryable_statuses
        self.sleep = sleep
        self.headers = {"User-Agent": INTELLIGENCE_USER_AGENT, **(headers or {})}
        self._throttle_lock = threading.Lock()
        self._next_request_at = 0.0
        self._cooldown_until = 0.0
        self._cooldown_reason: str | None = None
        self.rate_limit_events = 0

    @property
    def cooldown_remaining_seconds(self) -> float:
        return round(max(0.0, self._cooldown_until - time.monotonic()), 1)

    @property
    def cooldown_state(self) -> dict[str, Any]:
        remaining = self.cooldown_remaining_seconds
        return {
            "active": remaining > 0,
            "remaining_seconds": remaining,
            "reason": self._cooldown_reason if remaining > 0 else None,
            "rate_limit_events": self.rate_limit_events,
        }

    @staticmethod
    def _retry_after(headers: Any) -> float:
        try:
            return max(0.0, float((headers or {}).get("Retry-After", 0)))
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _set_rate_limit_cooldown(self, headers: Any) -> None:
        cooldown = max(
            self._retry_after(headers),
            self.jitter(
                self.rate_limit_backoff_seconds,
                self.maximum_rate_limit_backoff_seconds,
            ),
        )
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + cooldown)
        self._next_request_at = max(self._next_request_at, self._cooldown_until)
        self._cooldown_reason = "HTTP 429"
        self.rate_limit_events += 1

    def json(self, url: str, params: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            response: Any = None
            try:
                with self._throttle_lock:
                    wait = max(0.0, self._next_request_at - time.monotonic())
                    if wait:
                        self.sleep(wait)
                    interval = self.jitter(
                        self.delay_seconds, self.maximum_delay_seconds,
                    )
                    self._next_request_at = time.monotonic() + interval
                response = self.http_get(
                    url, params=params, headers=self.headers, timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError, TypeError) as error:
                last_error = error
                error_response = getattr(error, "response", None)
                if error_response is None:
                    error_response = response
                status = getattr(error_response, "status_code", None)
                headers = getattr(error_response, "headers", {}) or {}
                if status == 429:
                    self._set_rate_limit_cooldown(headers)
                if status in self.non_retryable_statuses:
                    break
                if attempt < self.retries:
                    if status != 429:
                        self.sleep(self.delay_seconds * (2 ** attempt))
        error_response = getattr(last_error, "response", None)
        status = getattr(error_response, "status_code", None)
        body = str(getattr(error_response, "text", "") or "")[:1000]
        raise PublicDataRequestError(
            str(last_error or "public data request failed"), status, body,
        ) from last_error

    def rate_limit(self) -> None:
        """Compatibility hook; request starts are throttled in ``json``."""


_SPORTS_CONTEXT = re.compile(
    r"\b(nhl|nba|nfl|mlb|ufc|fifa|uefa|esports?|match|game|score|playoffs?|"
    r"championship|league|tournament|coupe de france|oilers|fc|touchdown|goals?)\b", re.I,
)
_ENTERTAINMENT_CONTEXT = re.compile(
    r"\b(movie|film|album|song|episode|season|box office|netflix|oscar|grammy|"
    r"video game|steam|metacritic|actor|actress)\b", re.I,
)
_GEOPOLITICAL_ACTION = re.compile(
    r"\b(elect(?:ion|ed)?|president|prime minister|government|parliament|congress|"
    r"resign|impeach|out as (?:supreme leader|president|prime minister|chancellor)|"
    r"remov\w*.{0,30}from power|invad|offensive|war\b|ceasefire|air ?strike|missile|military|troops?|"
    r"sanction|tariff|embargo|blockade|treaty|summit|diplomatic|recognize|annex|border|"
    r"nuclear|uranium|reactor|terror|hostage|coup|referendum|peace deal|"
    r"central bank|interest rate|gdp|opec|oil production|shipping lane|"
    r"target(?:s|ed|ing)? shipping|sign(?:s|ed|ing)?.{0,40}(?:agreement|deal)|red sea)\w*",
    re.I,
)
_GENERIC_MEDIA = re.compile(
    r"\b(say|says|said|mention|post|tweet|speech|word|phrase|headline|attend|wear)\b",
    re.I,
)
_ADDITIONAL_GEOPOLITICAL_ENTITIES = (
    "afghanistan", "argentina", "australia", "belarus", "brazil", "canada",
    "colombia", "cuba", "denmark", "egypt", "ethiopia", "european union",
    "gaza", "greenland", "haiti", "hong kong", "indonesia", "lebanon",
    "libya", "mexico", "myanmar", "new zealand", "nigeria", "palestine",
    "philippines", "poland", "serbia", "somalia", "sudan", "turkey",
    "türkiye", "united arab emirates", "venezuela", "nicolás maduro",
    "nicolas maduro", "narendra modi", "recep tayyip erdoğan", "erdogan",
    "keir starmer", "emmanuel macron", "javier milei", "lula", "kim jong un",
)


def _contains_alias(text: str, alias: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(alias.lower())}(?!\w)", text.lower()))


def _geopolitical_entities(text: str) -> set[str]:
    entities = {
        f"country:{country}" for country, aliases in COUNTRIES.items()
        if any(_contains_alias(text, alias) for alias in aliases)
    }
    entities.update(
        f"actor:{actor}" for actor, aliases in ACTORS.items()
        if any(_contains_alias(text, alias) for alias in aliases)
    )
    entities.update(
        f"entity:{entity}" for entity in _ADDITIONAL_GEOPOLITICAL_ENTITIES
        if _contains_alias(text, entity)
    )
    return entities


def _strict_geopolitical_category(raw: dict[str, Any]) -> tuple[str | None, str]:
    """Require both geopolitical context and a known country/actor entity."""
    question = str(raw.get("question") or "").strip()
    event_text = " ".join(
        str(event.get("title") or event.get("description") or "")
        for event in raw.get("events", []) if isinstance(event, dict)
    )
    context = f"{question} {event_text}".strip()
    if not question:
        return None, "incomplete_metadata"
    if _SPORTS_CONTEXT.search(context):
        return None, "sports_market"
    if _ENTERTAINMENT_CONTEXT.search(context):
        return None, "entertainment_market"
    countries = {
        country for country, aliases in COUNTRIES.items()
        if any(_contains_alias(context, alias) for alias in aliases)
    }
    actors = {
        actor for actor, aliases in ACTORS.items()
        if any(_contains_alias(context, alias) for alias in aliases)
    }
    additional_entities = {
        entity for entity in _ADDITIONAL_GEOPOLITICAL_ENTITIES
        if _contains_alias(context, entity)
    }
    if not countries and not actors and not additional_entities:
        return None, "no_known_geopolitical_entity"
    if not _GEOPOLITICAL_ACTION.search(context):
        return None, "insufficient_geopolitical_context"
    if _GENERIC_MEDIA.search(question):
        return None, "generic_actor_mention"
    classified = MarketClassifier().classify({"question": context})
    if classified.event_type == EventType.OTHER:
        return "POLITICAL", "selected"
    return classified.event_type.name, "selected"


_CLUSTER_STOP_WORDS = {
    "a", "an", "and", "as", "at", "be", "before", "by", "during", "for",
    "from", "in", "is", "it", "most", "next", "no", "of", "on", "or",
    "the", "their", "there", "this", "to", "under", "up", "will", "with",
    "yes", "occur", "qualifying", "another", "country", "result", "odds",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
}


def _event_tokens(question: str) -> set[str]:
    text = question.lower().replace("u.s.", "us").replace("u.k.", "uk")
    return {
        token for token in re.findall(r"[a-z][a-z'-]+", text)
        if token not in _CLUSTER_STOP_WORDS and len(token) > 1
    }


def _same_event_family(left: HistoricalMarketMetadata, right: HistoricalMarketMetadata) -> bool:
    if left.category != right.category:
        return False
    left_close, right_close = _timestamp(left.actual_close_at), _timestamp(right.actual_close_at)
    if left_close is None or right_close is None or abs(left_close - right_close) > timedelta(days=7):
        return False
    left_context = re.split(r"\b(?:be|occur|held) in\b", left.question, maxsplit=1, flags=re.I)[0]
    right_context = re.split(r"\b(?:be|occur|held) in\b", right.question, maxsplit=1, flags=re.I)[0]
    left_entities = _geopolitical_entities(left_context)
    right_entities = _geopolitical_entities(right_context)
    shared_entities = left_entities & right_entities
    if not shared_entities:
        return False
    if max(len(left_entities), len(right_entities)) >= 2 and len(shared_entities) < 2:
        return False
    left_tokens, right_tokens = _event_tokens(left.question), _event_tokens(right.question)
    if not left_tokens or not right_tokens:
        return False
    intersection = len(left_tokens & right_tokens)
    similarity = intersection / len(left_tokens | right_tokens)
    containment = intersection / min(len(left_tokens), len(right_tokens))
    return similarity >= 0.55 or (intersection >= 4 and containment >= 0.75)


def analyze_market_universe(
    markets: list[HistoricalMarketMetadata], expected_months: tuple[str, ...] | None = None,
    sparse_threshold: int = 10, largest_limit: int = 10,
) -> MarketUniverseQualityReport:
    """Analyze contract concentration without changing the selected universe."""
    parents = list(range(len(markets)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = root(left), root(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(markets)):
        for right in range(left + 1, len(markets)):
            if _same_event_family(markets[left], markets[right]):
                union(left, right)
    grouped: dict[int, list[HistoricalMarketMetadata]] = {}
    for index, market in enumerate(markets):
        grouped.setdefault(root(index), []).append(market)
    clusters: list[EventCluster] = []
    for members in grouped.values():
        ordered = sorted(members, key=lambda item: item.market_id)
        identity = hashlib.sha256(
            "|".join(item.market_id for item in ordered).encode("utf-8")
        ).hexdigest()[:16]
        label = min((item.question for item in ordered), key=lambda value: (len(value), value))
        clusters.append(EventCluster(
            cluster_id=identity, label=label, category=ordered[0].category,
            market_count=len(ordered), market_ids=tuple(item.market_id for item in ordered),
            actual_close_months=tuple(sorted({item.actual_close_at[:7] for item in ordered})),
        ))
    clusters.sort(key=lambda item: (-item.market_count, item.label, item.cluster_id))
    selected_by_month = dict(sorted(collections.Counter(
        item.actual_close_at[:7] for item in markets
    ).items()))
    categories = dict(sorted(collections.Counter(item.category for item in markets).items()))
    size_distribution = dict(sorted(
        ((str(size), count) for size, count in collections.Counter(
            item.market_count for item in clusters
        ).items()), key=lambda item: int(item[0]),
    ))
    cluster_months = dict(sorted(collections.Counter(
        month for cluster in clusters for month in cluster.actual_close_months
    ).items()))
    months = expected_months or tuple(selected_by_month)
    warnings = tuple(
        f"{month}: {selected_by_month.get(month, 0)} selected markets "
        f"across {cluster_months.get(month, 0)} event clusters"
        for month in months if selected_by_month.get(month, 0) < sparse_threshold
    )
    return MarketUniverseQualityReport(
        generated_at=datetime.now(timezone.utc).isoformat(), total_markets=len(markets),
        unique_event_clusters=len(clusters),
        singleton_clusters=sum(cluster.market_count == 1 for cluster in clusters),
        effective_independence_percentage=round(len(clusters) / len(markets) * 100, 2)
        if markets else 0.0,
        selected_markets_by_month=selected_by_month, category_distribution=categories,
        cluster_size_distribution=size_distribution, clusters_by_close_month=cluster_months,
        sparse_month_warnings=warnings, largest_clusters=tuple(clusters[:largest_limit]),
    )


class HistoricalMarketSelector:
    """Discover Gamma metadata, filter locally, and persist a stable denominator."""

    selector_version = "4"

    def __init__(
        self, store: HistoricalMarketUniverseStore, http_get: HttpGet = requests.get,
        timeout: float = REQUEST_TIMEOUT, retries: int = 2, delay_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep, page_size: int = 100,
        checkpoint: CollectionCheckpoint | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.store = store
        self.reader = RetryingReader(http_get, timeout, retries, delay_seconds, sleep)
        self.page_size = page_size
        self.checkpoint = checkpoint or CollectionCheckpoint(store.path.parent / "checkpoint.json")
        self.progress = progress

    def select(
        self, start: datetime, end: datetime, max_pages: int | None = None,
        refresh: bool = False,
    ) -> tuple[list[HistoricalMarketMetadata], MarketSelectionReport]:
        start, end = _utc_range(start, end)
        previous = self.store.report()
        if (
            not refresh and previous is not None and previous.discovery_complete
            and previous.start == start.isoformat() and previous.end == end.isoformat()
            and previous.selector_version == self.selector_version
        ):
            return self.store.load(), previous
        started = time.monotonic()
        selected: dict[str, HistoricalMarketMetadata] = {}
        exclusions: dict[str, dict[str, str]] = {}
        discovered_months: dict[str, int] = {}
        selected_months: dict[str, int] = {}
        categories: dict[str, int] = {}
        exclusion_counts: dict[str, int] = {}
        seen_ids: set[str] = set()
        cursor: str | None = None
        pages = scanned = denominator = 0
        complete = True
        stop = False
        monthly_windows = _monthly_windows(start, end)
        scan_windows = [(*window, "true") for window in monthly_windows]
        if monthly_windows:
            scan_windows.append((*monthly_windows[-1], "false"))
        for partition_start, partition_end, ascending in scan_windows:
            cursor = None
            partition_pages = 0
            while max_pages is None or partition_pages < max_pages:
                params: dict[str, Any] = {
                    "closed": "true", "limit": self.page_size,
                    "order": "closedTime", "ascending": ascending,
                    "end_date_min": partition_start.isoformat(),
                    "end_date_max": partition_end.isoformat(),
                }
                if cursor:
                    params["after_cursor"] = cursor
                try:
                    payload = self.reader.json(GAMMA_KEYSET_MARKETS_URL, params)
                except PublicDataRequestError:
                    complete = False
                    stop = True
                    break
                legacy = isinstance(payload, list)
                markets = payload if legacy else payload.get("markets", []) if isinstance(payload, dict) else []
                next_cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
                if not markets:
                    break
                pages += 1
                partition_pages += 1
                for raw in markets:
                    if not isinstance(raw, dict):
                        continue
                    scanned += 1
                    market_id = str(raw.get("id") or raw.get("conditionId") or f"row-{scanned}")
                    if market_id in seen_ids:
                        continue
                    seen_ids.add(market_id)
                    actual_close = _timestamp(raw.get("closedTime"))
                    if actual_close is None:
                        reason = "missing_actual_close"
                    elif not start <= actual_close < end:
                        reason = "actual_close_out_of_range"
                    else:
                        denominator += 1
                        month = actual_close.strftime("%Y-%m")
                        discovered_months[month] = discovered_months.get(month, 0) + 1
                        category, reason = _strict_geopolitical_category(raw)
                        if category is not None:
                            try:
                                metadata = self._metadata(raw, category, actual_close)
                            except ValueError:
                                reason = "incomplete_metadata"
                            else:
                                selected[metadata.market_id] = metadata
                                selected_months[month] = selected_months.get(month, 0) + 1
                                categories[category] = categories.get(category, 0) + 1
                                continue
                    exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                    exclusions[market_id] = {"market_id": market_id, "reason": reason}
                _emit(self.progress, started, stage="market_selection", pages_scanned=pages,
                      markets_scanned=scanned, markets_discovered=denominator,
                      markets_selected=len(selected))
                if legacy:
                    cursor = None
                    stop = True
                    break
                if not next_cursor:
                    cursor = None
                    break
                cursor = str(next_cursor)
                self.checkpoint.update(
                    "market_selection", start=start.isoformat(), end=end.isoformat(),
                    partition_start=partition_start.isoformat(), ascending=ascending, cursor=cursor,
                    pages_scanned=pages, complete=False,
                )
            if stop:
                break
            if max_pages is not None and partition_pages >= max_pages and cursor:
                complete = False
        if max_pages is not None and cursor:
            complete = False
        report = MarketSelectionReport(
            start=start.isoformat(), end=end.isoformat(), discovery_complete=complete,
            pages_scanned=pages, markets_scanned=scanned,
            discovered_market_denominator=denominator,
            selected_market_denominator=len(selected),
            markets_discovered_by_month=dict(sorted(discovered_months.items())),
            markets_selected_by_month=dict(sorted(selected_months.items())),
            excluded_counts_by_reason=dict(sorted(exclusion_counts.items())),
            geopolitical_category_distribution=dict(sorted(categories.items())),
            selector_version=self.selector_version,
        )
        self.store.save_selection(list(selected.values()), report, list(exclusions.values()))
        self.checkpoint.update(
            "market_selection", **asdict(report), cursor=None if complete else cursor,
            complete=complete,
        )
        return list(selected.values()), report

    @staticmethod
    def _metadata(
        raw: dict[str, Any], category: str, actual_close: datetime,
    ) -> HistoricalMarketMetadata:
        created = _timestamp(raw.get("createdAt") or raw.get("creationDate"))
        outcomes = tuple(str(item) for item in _items(raw.get("outcomes")))
        tokens = tuple(str(item) for item in _items(raw.get("clobTokenIds")))
        if created is None or len(outcomes) < 2 or len(tokens) < len(outcomes):
            raise ValueError("incomplete market metadata")
        resolution = HistoricalCoverageProbe._resolution(
            list(outcomes), _items(raw.get("outcomePrices")),
        )
        status = str(raw.get("resolutionStatus") or raw.get("umaResolutionStatus") or (
            "resolved" if resolution is not None else "unresolved"
        ))
        return HistoricalMarketMetadata(
            market_id=str(raw.get("id") or raw.get("conditionId") or ""),
            condition_id=_optional_string(raw.get("conditionId")), question=str(raw.get("question")),
            created_at=_iso(created) or "", scheduled_end_at=_iso(_timestamp(
                raw.get("endDate") or raw.get("endDateIso")
            )), actual_close_at=_iso(actual_close) or "", resolution_status=status,
            category=category, outcomes=outcomes, token_ids=tokens,
            outcome_prices=tuple(str(item) for item in _items(raw.get("outcomePrices"))),
            volume=_optional_float(raw.get("volume")), liquidity=_optional_float(raw.get("liquidity")),
        )


class HistoricalMarketCollector:
    """Collect closed Gamma markets and their public CLOB candle histories."""

    def __init__(
        self, store: HistoricalMarketDatasetStore,
        http_get: HttpGet = requests.get, timeout: float = REQUEST_TIMEOUT,
        retries: int = 2, delay_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep, page_size: int = 100,
        checkpoint_size: int = 1, workers: int = 4,
        history_window: timedelta = timedelta(days=7),
        checkpoint: CollectionCheckpoint | None = None,
        progress: ProgressCallback | None = None,
        selector: HistoricalMarketSelector | None = None,
        manifest: CollectionManifestStore | None = None,
        universe: HistoricalMarketUniverseStore | None = None,
    ) -> None:
        self.store = store
        self.reader = RetryingReader(http_get, timeout, retries, delay_seconds, sleep)
        self.page_size = page_size
        self.checkpoint_size = max(1, checkpoint_size)
        self.workers = max(1, workers)
        if history_window.total_seconds() <= 0:
            raise ValueError("history_window must be positive")
        self.history_window = history_window
        self.checkpoint = checkpoint or CollectionCheckpoint(store.path.parent / "checkpoint.json")
        self.progress = progress
        self.selector = selector
        self.manifest = manifest
        self.universe = universe
        if (manifest is None) != (universe is None):
            raise ValueError("manifest and universe must be configured together")

    def collect(self, start: datetime, end: datetime, max_pages: int | None = None) -> CollectionResult:
        start, end = _utc_range(start, end)
        started = time.monotonic()
        existing = {item.market_id: item for item in self.store.load()}
        state = self.checkpoint.section("markets")
        failures = list(state.get("failures", []))
        exclusions_by_market = {
            str(item.get("market_id")): item
            for item in state.get("market_exclusions", []) if isinstance(item, dict)
        }
        candidates_by_id: dict[str, dict[str, Any]] = {}
        incomplete = 0
        cursor: str | None = None
        pages = 0
        finished = False
        discovery_complete = True
        if self.manifest is not None and self.universe is not None:
            manifest, metadata = self.manifest.validate(self.universe)
            if start.isoformat() != manifest.evaluation_start or end.isoformat() != manifest.evaluation_end:
                raise ValueError("collection range does not match the frozen manifest")
            candidates_by_id = {
                item.market_id: item.as_gamma_market() for item in metadata
            }
        elif self.selector is not None:
            metadata, selection_report = self.selector.select(start, end, max_pages=max_pages)
            candidates_by_id = {
                item.market_id: item.as_gamma_market() for item in metadata
            }
            pages = selection_report.pages_scanned
            discovery_complete = selection_report.discovery_complete
        while (
            self.selector is None and self.manifest is None and not finished
            and (max_pages is None or pages < max_pages)
        ):
            try:
                params: dict[str, Any] = {
                    "closed": "true", "limit": self.page_size,
                    "order": "closedTime", "ascending": "true",
                    "end_date_min": start.isoformat(), "end_date_max": end.isoformat(),
                }
                if cursor:
                    params["after_cursor"] = cursor
                payload = self.reader.json(GAMMA_KEYSET_MARKETS_URL, params)
            except RuntimeError as error:
                failure = f"Gamma page {pages + 1}: {error}"
                if failure not in failures:
                    failures.append(failure)
                discovery_complete = False
                break
            legacy_response = isinstance(payload, list)
            markets = payload if legacy_response else (
                payload.get("markets", []) if isinstance(payload, dict) else []
            )
            next_cursor = payload.get("next_cursor") if isinstance(payload, dict) else None
            if not markets:
                break
            pages += 1
            for raw in markets:
                if not isinstance(raw, dict):
                    incomplete += 1
                    continue
                scheduled_end = _timestamp(
                    raw.get("endDate") or raw.get("endDateIso") or raw.get("closedTime")
                )
                if scheduled_end is None:
                    incomplete += 1
                    continue
                if scheduled_end < start:
                    continue
                if scheduled_end > end:
                    finished = True
                    continue
                market_id = str(raw.get("id") or raw.get("conditionId") or "")
                if market_id:
                    candidates_by_id[market_id] = raw
            if legacy_response or not next_cursor:
                break
            cursor = str(next_cursor)
            self.reader.rate_limit()
            self.checkpoint.update(
                "markets", discovery_cursor=cursor, discovery_pages=pages,
                discovered_market_denominator=len(candidates_by_id), complete=False,
            )
            _emit(self.progress, started, stage="market_discovery",
                  markets_discovered=len(candidates_by_id))

        if max_pages is not None and pages >= max_pages and cursor:
            discovery_complete = False
        if discovery_complete:
            failures = [item for item in failures if not item.startswith("Gamma page ")]
        candidates = list(candidates_by_id.values())
        total = len(candidates)
        completed = [
            raw for raw in candidates
            if str(raw.get("id") or raw.get("conditionId") or "") in existing
            and existing[str(raw.get("id") or raw.get("conditionId") or "")].has_valid_price_history
        ]
        pending = [raw for raw in candidates if raw not in completed]
        processed = len(completed)
        successful = len(completed)
        failed = 0
        added = 0
        duplicates = len(completed)
        buffer: list[HistoricalMarketRecord] = []
        _emit(self.progress, started, stage="markets", markets_processed=processed,
              markets_total=total, markets_remaining=max(0, total - processed),
              successful_price_histories=successful, failed_markets=failed,
              price_coverage_percentage=round(successful / total * 100, 2) if total else 0.0)

        def flush() -> None:
            nonlocal added, duplicates, buffer
            if not buffer:
                return
            new, repeated = self.store.upsert(buffer)
            added += new
            duplicates += repeated
            buffer = []
            self.checkpoint.update(
                "markets", failures=failures, markets_processed=processed,
                markets_total=total, successful_price_histories=successful,
                failed_markets=failed, incomplete_markets=incomplete,
                market_exclusions=list(exclusions_by_market.values()),
                discovered_market_denominator=total,
                discovery_pages=pages, discovery_complete=discovery_complete,
                complete=False,
            )

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {executor.submit(self._market, raw): raw for raw in pending}
                for future in as_completed(futures):
                    raw = futures[future]
                    market_id = str(raw.get("id") or raw.get("conditionId") or "unknown")
                    processed += 1
                    try:
                        buffer.append(future.result())
                        successful += 1
                        failures = [
                            item for item in failures
                            if not item.startswith(f"market {market_id}:")
                        ]
                        exclusions_by_market.pop(market_id, None)
                    except ValueError:
                        incomplete += 1
                        failed += 1
                    except MarketCollectionError as error:
                        exclusion = asdict(error.exclusion)
                        exclusions_by_market[market_id] = exclusion
                        if error.exclusion.reason == "incomplete_metadata":
                            incomplete += 1
                        failure = f"market {market_id} [{error.exclusion.reason}]: {error}"
                        failures = [
                            item for item in failures
                            if not item.startswith(f"market {market_id}")
                        ]
                        failures.append(failure)
                        failed += 1
                    except RuntimeError as error:
                        failure = f"market {market_id}: {error}"
                        if failure not in failures:
                            failures.append(failure)
                        failed += 1
                    if len(buffer) >= self.checkpoint_size or processed == total:
                        flush()
                    else:
                        self.checkpoint.update(
                            "markets", failures=failures, markets_processed=processed,
                            markets_total=total, successful_price_histories=successful,
                            failed_markets=failed, incomplete_markets=incomplete,
                            market_exclusions=list(exclusions_by_market.values()),
                            discovered_market_denominator=total,
                            discovery_pages=pages, discovery_complete=discovery_complete,
                            complete=False,
                        )
                    _emit(self.progress, started, stage="markets", markets_processed=processed,
                          markets_total=total, markets_remaining=max(0, total - processed),
                          successful_price_histories=successful, failed_markets=failed,
                          price_coverage_percentage=round(successful / total * 100, 2)
                          if total else 0.0)
        finally:
            flush()
        self.checkpoint.update(
            "markets", failures=failures, markets_processed=processed,
            markets_total=total, successful_price_histories=successful,
            failed_markets=failed, incomplete_markets=incomplete,
            market_exclusions=list(exclusions_by_market.values()),
            discovered_market_denominator=total,
            discovery_pages=pages, discovery_cursor=None,
            discovery_complete=discovery_complete,
            complete=discovery_complete and processed == total and failed == 0,
        )
        return CollectionResult(successful, added, duplicates, incomplete, tuple(failures))

    def _market(self, raw: dict[str, Any]) -> HistoricalMarketRecord:
        market_id = str(raw.get("id") or raw.get("conditionId") or "")
        question = str(raw.get("question") or "")
        created = _timestamp(raw.get("createdAt") or raw.get("creationDate"))
        closed = _timestamp(raw.get("closedTime") or raw.get("endDate"))
        outcomes = tuple(str(item) for item in _items(raw.get("outcomes")))
        token_values = [str(item) for item in _items(raw.get("clobTokenIds"))]
        if not market_id or not question or len(outcomes) < 2:
            raise MarketCollectionError(MarketExclusion(
                market_id or "unknown", "incomplete_metadata",
                "market identity, question, or outcomes are incomplete",
            ))
        if created is None or closed is None or created >= closed:
            raise MarketCollectionError(MarketExclusion(
                market_id, "invalid_timestamps", "creation and close timestamps are invalid",
            ))
        invalid_tokens = [
            token for token in token_values
            if not HistoricalCoverageProbe._valid_token_id(token)
        ]
        if len(token_values) < len(outcomes) or invalid_tokens:
            raise MarketCollectionError(MarketExclusion(
                market_id, "invalid_token", "market contains a missing or invalid CLOB token",
                token_id=invalid_tokens[0] if invalid_tokens else None,
            ))
        tokens = {
            outcome.upper(): token_values[index]
            for index, outcome in enumerate(outcomes)
            if index < len(token_values)
            and HistoricalCoverageProbe._valid_token_id(token_values[index])
        }
        if len(tokens) < 2:
            raise ValueError("incomplete market tokens")
        histories: dict[str, tuple[PriceCandle, ...]] = {}
        for outcome, token in tokens.items():
            candles: dict[str, PriceCandle] = {}
            chunk_start = created
            history_end = closed + timedelta(days=1)
            while chunk_start < history_end:
                chunk_end = min(chunk_start + self.history_window, history_end)
                try:
                    payload = self.reader.json(CLOB_HISTORY_URL, {
                        "market": token, "startTs": int(chunk_start.timestamp()),
                        "endTs": int(chunk_end.timestamp()), "fidelity": 60,
                    })
                except PublicDataRequestError as error:
                    raise MarketCollectionError(_classify_clob_failure(
                        raw, market_id, outcome, token, error,
                    )) from error
                raw_history = payload.get("history", []) if isinstance(payload, dict) else []
                for point in raw_history:
                    timestamp = _timestamp(point.get("t")) if isinstance(point, dict) else None
                    try:
                        price = float(point.get("p")) if isinstance(point, dict) else -1.0
                        candle = PriceCandle(_iso(timestamp) or "", price)
                    except (TypeError, ValueError):
                        continue
                    candles[candle.timestamp] = candle
                chunk_start = chunk_end
            histories[outcome] = tuple(candles[key] for key in sorted(candles))
            if not histories[outcome]:
                raise MarketCollectionError(MarketExclusion(
                    market_id, "unavailable_history",
                    "CLOB returned no historical prices", outcome, token, 200,
                ))
            self.reader.rate_limit()
        return HistoricalMarketRecord(
            market_id=market_id, condition_id=str(raw.get("conditionId")) if raw.get("conditionId") else None,
            question=question, created_at=_iso(created) or "", closed_at=_iso(closed) or "",
            outcomes=outcomes, token_ids=tokens,
            resolution_outcome=HistoricalCoverageProbe._resolution(
                list(outcomes), _items(raw.get("outcomePrices")),
            ),
            price_history=histories, volume=_optional_float(raw.get("volume")),
            liquidity=_optional_float(raw.get("liquidity")),
            category=_market_category(raw),
            scheduled_end_at=_iso(_timestamp(
                raw.get("endDate") or raw.get("endDateIso") or raw.get("closedTime")
            )),
        )


class GDELTIntelligenceCollector:
    """Collect timestamped GDELT articles in bounded, retryable windows."""

    def __init__(
        self, store: HistoricalIntelligenceDatasetStore,
        http_get: HttpGet = requests.get, timeout: float = REQUEST_TIMEOUT,
        retries: int = 4, delay_seconds: float = 6.0,
        sleep: Callable[[float], None] = time.sleep,
        window: timedelta = timedelta(days=1), query: str = "geopolitics",
        checkpoint: CollectionCheckpoint | None = None,
        progress: ProgressCallback | None = None,
        max_consecutive_failures: int = 12,
        max_rate_limit_failures_per_run: int = 2,
        rate_limit_backoff_seconds: float = 30.0,
        maximum_delay_seconds: float | None = None,
        maximum_rate_limit_backoff_seconds: float | None = None,
        jitter: Callable[[float, float], float] = random.uniform,
        result_limit: int = GDELT_ARTICLE_RESULT_LIMIT,
        minimum_window: timedelta = GDELT_MINIMUM_PARTITION,
        manifest: HistoricalIntelligenceManifestStore | None = None,
        max_requests_per_run: int = GDELT_LOGICAL_REQUEST_BUDGET,
    ) -> None:
        if window.total_seconds() <= 0 or minimum_window.total_seconds() <= 0:
            raise ValueError("window must be positive")
        if (
            minimum_window > window or result_limit <= 0 or max_requests_per_run <= 0
            or max_rate_limit_failures_per_run <= 0
        ):
            raise ValueError("invalid adaptive GDELT partition settings")
        self.store = store
        self.reader = RetryingReader(
            http_get, timeout, retries, delay_seconds, sleep,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            maximum_delay_seconds=maximum_delay_seconds,
            maximum_rate_limit_backoff_seconds=maximum_rate_limit_backoff_seconds,
            jitter=jitter,
        )
        self.window = window
        self.query = query
        self.checkpoint = checkpoint or CollectionCheckpoint(store.path.parent / "checkpoint.json")
        self.progress = progress
        self.max_consecutive_failures = max(1, max_consecutive_failures)
        self.max_rate_limit_failures_per_run = max_rate_limit_failures_per_run
        self.result_limit = result_limit
        self.minimum_window = minimum_window
        self.manifest = manifest
        self.max_requests_per_run = max_requests_per_run

    def collect(self, start: datetime, end: datetime) -> CollectionResult:
        start, end = _utc_range(start, end)
        started = time.monotonic()
        state = self.checkpoint.section("intelligence")
        completed = set(state.get("completed_windows", []))
        failures = list(state.get("failures", []))
        adaptive = dict(state.get("adaptive_partitions", {}))
        # Legacy daily windows were marked complete even when ArticleList hit its
        # hard result limit. Reopen those roots so they receive adaptive leaves.
        legacy_records = self.store.load()
        for window_key in tuple(completed):
            if window_key in adaptive:
                continue
            try:
                raw_start, raw_end = window_key.split("..", 1)
                legacy_start, legacy_end = _timestamp(raw_start), _timestamp(raw_end)
            except ValueError:
                continue
            if legacy_start is None or legacy_end is None:
                continue
            count = sum(
                item.source == "GDELT"
                and legacy_start <= (_timestamp(item.published_at) or end) < legacy_end
                for item in legacy_records
            )
            if count >= self.result_limit:
                completed.remove(window_key)
        incomplete = 0
        cursor = start
        total_windows = max(1, int((end - start + self.window - timedelta.resolution) / self.window))
        windows: list[tuple[datetime, datetime, str]] = []
        while cursor < end:
            window_end = min(cursor + self.window, end)
            windows.append((cursor, window_end, f"{cursor.isoformat()}..{window_end.isoformat()}"))
            cursor = window_end
        queued = [key for key in state.get("retry_queue", []) if key not in completed]
        resumed_windows = len(queued)
        # Cover untouched windows before retrying known 429/timeout windows so a
        # small poisoned queue cannot block resumable progress across the range.
        windows.sort(key=lambda item: (item[2] in queued, item[0]))
        windows_attempted = 0
        consecutive_failures = 0
        collected = 0
        added = 0
        duplicates = 0
        retry_queue = list(queued)
        requests_made = 0
        budget_exhausted = False
        persistent_rate_limit_failures = 0
        rate_limit_pause_triggered = False

        def progress_values() -> dict[str, Any]:
            remaining_windows = max(0, total_windows - len(completed))
            remaining_requests = 0
            for _, _, key in windows:
                if key in completed:
                    continue
                leaves = adaptive.get(key)
                remaining_requests += sum(
                    item.get("status") != "complete" for item in leaves
                ) if isinstance(leaves, list) else 1
            average_pacing = (
                self.reader.delay_seconds + self.reader.maximum_delay_seconds
            ) / 2
            return {
                "remaining_windows": remaining_windows,
                "retry_queue_size": len(retry_queue),
                "cooldown": self.reader.cooldown_state,
                "persistent_rate_limit_failures": persistent_rate_limit_failures,
                "rate_limit_pause_triggered": rate_limit_pause_triggered,
                "estimated_remaining_work": {
                    "logical_requests_lower_bound": remaining_requests,
                    "minutes_at_normal_pacing": round(
                        remaining_requests * average_pacing / 60, 1,
                    ),
                },
            }

        for cursor, window_end, window_key in windows:
            if window_key in completed:
                if self.manifest is not None:
                    self.manifest.update_status(
                        HistoricalIntelligenceManifestStore._partition_id(
                            "GDELT", cursor, window_end,
                        ),
                        "complete", migrated_from_checkpoint=True,
                    )
                _emit(
                    self.progress, started, stage="intelligence",
                    windows_completed=len(completed), windows_total=total_windows,
                    resumed_windows=resumed_windows, **progress_values(),
                )
                continue
            if window_key not in retry_queue:
                retry_queue.append(window_key)
            partition_id = HistoricalIntelligenceManifestStore._partition_id(
                "GDELT", cursor, window_end,
            )
            if self.manifest is not None:
                self.manifest.update_status(partition_id, "collecting")
            self.checkpoint.update(
                "intelligence", completed_windows=sorted(completed), failures=failures,
                retry_queue=retry_queue, current_window=window_key,
                windows_completed=len(completed), windows_attempted=windows_attempted,
                windows_attempted_total=int(state.get("windows_attempted_total", 0))
                + windows_attempted,
                windows_total=total_windows, complete=False,
                adaptive_partitions=adaptive,
                cooldown=self.reader.cooldown_state,
                rate_limit_events_this_run=self.reader.rate_limit_events,
            )
            leaves = adaptive.get(window_key) or [{
                "start": cursor.isoformat(), "end": window_end.isoformat(), "status": "pending",
            }]
            root_failed = False
            root_deferred = False
            saturated = False
            while True:
                pending = next((item for item in leaves if item.get("status") != "complete"), None)
                if pending is None:
                    break
                leaf_start = _timestamp(pending.get("start"))
                leaf_end = _timestamp(pending.get("end"))
                if leaf_start is None or leaf_end is None or leaf_start >= leaf_end:
                    raise ValueError("invalid adaptive GDELT checkpoint partition")
                if requests_made >= self.max_requests_per_run:
                    root_deferred = budget_exhausted = True
                    break
                try:
                    requests_made += 1
                    payload = self.reader.json(GDELT_DOC_URL, {
                        "query": self.query, "mode": "ArtList", "format": "json",
                        "maxrecords": self.result_limit,
                        "startdatetime": leaf_start.strftime("%Y%m%d%H%M%S"),
                        "enddatetime": leaf_end.strftime("%Y%m%d%H%M%S"),
                    })
                    articles = payload.get("articles", []) if isinstance(payload, dict) else []
                    if len(articles) >= self.result_limit:
                        duration = leaf_end - leaf_start
                        if duration <= self.minimum_window:
                            pending["status"] = "saturated"
                            saturated = root_failed = True
                            failure = f"GDELT {window_key}: result limit reached at minimum window"
                            if failure not in failures:
                                failures.append(failure)
                            break
                        midpoint = leaf_start + duration / 2
                        index = leaves.index(pending)
                        leaves[index:index + 1] = [
                            {"start": leaf_start.isoformat(), "end": midpoint.isoformat(),
                             "status": "pending"},
                            {"start": midpoint.isoformat(), "end": leaf_end.isoformat(),
                             "status": "pending"},
                        ]
                        adaptive[window_key] = leaves
                        if self.manifest is not None:
                            self.manifest.update_status(
                                partition_id, "split", leaf_count=len(leaves),
                            )
                        self.checkpoint.update(
                            "intelligence", adaptive_partitions=adaptive,
                            current_window=window_key, retry_queue=retry_queue,
                        )
                        continue
                    records: list[HistoricalIntelligenceItem] = []
                    for article in articles:
                        item = self._article(
                            article, self.query, window_key,
                            leaf_start.isoformat(), leaf_end.isoformat(),
                        )
                        if item is None:
                            incomplete += 1
                        elif leaf_start <= (_timestamp(item.published_at) or end) < leaf_end:
                            records.append(item)
                    new, repeated = self.store.upsert(records)
                    collected += len(records)
                    added += new
                    duplicates += repeated
                    pending.update({"status": "complete", "records": len(records)})
                    adaptive[window_key] = leaves
                    self.checkpoint.update(
                        "intelligence", adaptive_partitions=adaptive,
                        current_window=window_key, retry_queue=retry_queue,
                    )
                    self.reader.rate_limit()
                except RuntimeError as error:
                    pending["status"] = "failed"
                    adaptive[window_key] = leaves
                    failure = f"GDELT {window_key}: {error}"
                    if failure not in failures:
                        failures.append(failure)
                    root_failed = True
                    if getattr(error, "status_code", None) == 429:
                        persistent_rate_limit_failures += 1
                        if (
                            persistent_rate_limit_failures
                            >= self.max_rate_limit_failures_per_run
                        ):
                            rate_limit_pause_triggered = True
                    break
            if root_deferred:
                adaptive[window_key] = leaves
                if self.manifest is not None:
                    self.manifest.update_status(
                        partition_id, "split" if len(leaves) > 1 else "pending",
                        leaf_count=len(leaves), deferred_by_request_budget=True,
                    )
            elif not root_failed:
                completed.add(window_key)
                failures = [item for item in failures if not item.startswith(f"GDELT {window_key}:")]
                retry_queue = [item for item in retry_queue if item != window_key]
                consecutive_failures = 0
                if self.manifest is not None:
                    self.manifest.update_status(
                        partition_id, "complete", leaf_count=len(leaves),
                        records=sum(int(item.get("records", 0)) for item in leaves),
                    )
            else:
                if window_key not in retry_queue:
                    retry_queue.append(window_key)
                consecutive_failures += 1
                if self.manifest is not None:
                    self.manifest.update_status(
                        partition_id, "saturated" if saturated else "failed",
                        leaf_count=len(leaves),
                    )
            windows_attempted += 1
            self.checkpoint.update(
                "intelligence", completed_windows=sorted(completed), failures=failures,
                retry_queue=retry_queue,
                current_window=None,
                windows_completed=len(completed), windows_attempted=windows_attempted,
                windows_attempted_total=int(state.get("windows_attempted_total", 0))
                + windows_attempted,
                windows_total=total_windows,
                complete=False,
                adaptive_partitions=adaptive,
                requests_this_run=requests_made,
                cooldown=self.reader.cooldown_state,
                rate_limit_events_this_run=self.reader.rate_limit_events,
                persistent_rate_limit_failures_this_run=persistent_rate_limit_failures,
                rate_limit_pause_triggered=rate_limit_pause_triggered,
            )
            _emit(
                self.progress, started, stage="intelligence",
                windows_completed=len(completed), windows_total=total_windows,
                failed_windows=len(failures), resumed_windows=resumed_windows,
                attempted_this_run=windows_attempted, **progress_values(),
            )
            if consecutive_failures >= self.max_consecutive_failures:
                break
            if rate_limit_pause_triggered:
                break
            if budget_exhausted:
                break
            self.reader.rate_limit()
        self.checkpoint.update(
            "intelligence", completed_windows=sorted(completed), failures=failures,
            retry_queue=retry_queue,
            current_window=None,
            windows_completed=len(completed), windows_attempted=windows_attempted,
            windows_attempted_total=int(state.get("windows_attempted_total", 0))
            + windows_attempted,
            windows_total=total_windows, adaptive_partitions=adaptive,
            requests_this_run=requests_made,
            complete=len(completed) == total_windows and not failures,
            cooldown=self.reader.cooldown_state,
            rate_limit_events_this_run=self.reader.rate_limit_events,
            persistent_rate_limit_failures_this_run=persistent_rate_limit_failures,
            rate_limit_pause_triggered=rate_limit_pause_triggered,
        )
        return CollectionResult(collected, added, duplicates, incomplete, tuple(failures))

    @staticmethod
    def _article(
        raw: Any, query: str = "geopolitics", root_partition: str | None = None,
        partition_start: str | None = None, partition_end: str | None = None,
    ) -> HistoricalIntelligenceItem | None:
        if not isinstance(raw, dict):
            return None
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or raw.get("url_mobile") or "").strip()
        published = _timestamp(raw.get("seendate"))
        if not title or not url or published is None:
            return None
        timestamp = _iso(published) or ""
        identity = hashlib.sha256(f"{url}|{timestamp}".encode("utf-8")).hexdigest()
        return HistoricalIntelligenceItem(
            record_id=identity, title=title, source="GDELT", source_url=url,
            published_at=timestamp, available_at=timestamp,
            source_domain=_optional_string(raw.get("domain")),
            source_country=_optional_string(raw.get("sourcecountry")),
            language=_optional_string(raw.get("language")),
            metadata={
                key: value for key, value in raw.items()
                if key not in {"title", "url", "url_mobile", "seendate"}
                and value is not None
            } | {
                "historical_provider": "GDELT", "query": query,
                "root_partition": root_partition,
                "partition_start": partition_start, "partition_end": partition_end,
                "availability_timestamp_policy": "gdelt.seendate_first_observed",
            },
        )


class ReliefWebHistoricalIntelligenceCollector:
    """Collect ReliefWeb reports by created-date day with resumable pagination."""

    provider = "ReliefWeb"
    availability_timestamp_policy = "reliefweb.date.created"

    def __init__(
        self, store: HistoricalIntelligenceDatasetStore,
        http_get: HttpGet = requests.get, timeout: float = REQUEST_TIMEOUT,
        retries: int = 4, delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        window: timedelta = timedelta(days=1), query: str = "",
        page_size: int = 1000, appname: str = RELIEFWEB_APPNAME,
        checkpoint: CollectionCheckpoint | None = None,
        progress: ProgressCallback | None = None,
        manifest: HistoricalIntelligenceManifestStore | None = None,
    ) -> None:
        if window.total_seconds() <= 0 or not 1 <= page_size <= 1000:
            raise ValueError("invalid ReliefWeb collection settings")
        self.store = store
        self.reader = RetryingReader(http_get, timeout, retries, delay_seconds, sleep)
        self.window = window
        self.query = query
        self.page_size = page_size
        self.appname = appname
        self.checkpoint = checkpoint or CollectionCheckpoint(store.path.parent / "checkpoint.json")
        self.progress = progress
        self.manifest = manifest

    def collect(self, start: datetime, end: datetime) -> CollectionResult:
        start, end = _utc_range(start, end)
        state = self.checkpoint.section("intelligence_reliefweb")
        completed = set(state.get("completed_windows", []))
        failures = list(state.get("failures", []))
        page_offsets = dict(state.get("page_offsets", {}))
        retry_queue = [
            item for item in state.get("retry_queue", []) if item not in completed
        ]
        collected = added = duplicates = incomplete = 0
        cursor = start
        windows: list[tuple[datetime, datetime, str]] = []
        while cursor < end:
            window_end = min(cursor + self.window, end)
            windows.append((cursor, window_end, f"{cursor.isoformat()}..{window_end.isoformat()}"))
            cursor = window_end
        authorization_blocked = False
        for cursor, window_end, window_key in windows:
            if window_key in completed:
                continue
            if window_key not in retry_queue:
                retry_queue.append(window_key)
            partition_id = HistoricalIntelligenceManifestStore._partition_id(
                self.provider, cursor, window_end,
            )
            if self.manifest is not None:
                self.manifest.update_status(partition_id, "collecting")
            offset = int(page_offsets.get(window_key, 0))
            window_records = 0
            try:
                while True:
                    params: dict[str, Any] = {
                        "appname": self.appname, "limit": self.page_size, "offset": offset,
                        "sort[]": "date.created:asc",
                        "filter[field]": "date.created",
                        "filter[value][from]": cursor.isoformat(),
                        "filter[value][to]": window_end.isoformat(),
                        "fields[include][]": [
                            "title", "body", "url", "date.created", "date.original",
                            "primary_country.name", "source.name",
                        ],
                    }
                    if self.query:
                        params["query[value]"] = self.query
                    payload = self.reader.json(RELIEFWEB_API_URL, params)
                    records = payload.get("data", []) if isinstance(payload, dict) else []
                    parsed: list[HistoricalIntelligenceItem] = []
                    for raw in records if isinstance(records, list) else []:
                        item = self._report(raw, window_key, cursor, window_end)
                        if item is None:
                            incomplete += 1
                        else:
                            parsed.append(item)
                    new, repeated = self.store.upsert(parsed)
                    collected += len(parsed)
                    window_records += len(parsed)
                    added += new
                    duplicates += repeated
                    offset += len(records)
                    page_offsets[window_key] = offset
                    self.checkpoint.update(
                        "intelligence_reliefweb", completed_windows=sorted(completed),
                        failures=failures, page_offsets=page_offsets,
                        retry_queue=retry_queue, current_window=window_key, complete=False,
                    )
                    total = payload.get("totalCount") if isinstance(payload, dict) else None
                    if not records or len(records) < self.page_size or (
                        isinstance(total, int) and offset >= total
                    ):
                        break
                    self.reader.rate_limit()
                completed.add(window_key)
                page_offsets.pop(window_key, None)
                retry_queue = [item for item in retry_queue if item != window_key]
                failures = [item for item in failures if not item.startswith(
                    f"ReliefWeb {window_key}:"
                )]
                if self.manifest is not None:
                    self.manifest.update_status(
                        partition_id, "complete", records=window_records,
                    )
            except RuntimeError as error:
                failure = f"ReliefWeb {window_key}: {error}"
                if failure not in failures:
                    failures.append(failure)
                if self.manifest is not None:
                    self.manifest.update_status(partition_id, "failed", offset=offset)
                authorization_blocked = isinstance(error, PublicDataRequestError) and (
                    error.status_code in {401, 403}
                )
            self.checkpoint.update(
                "intelligence_reliefweb", completed_windows=sorted(completed),
                failures=failures, page_offsets=page_offsets, retry_queue=retry_queue,
                current_window=None,
                windows_total=len(windows), windows_completed=len(completed),
                complete=len(completed) == len(windows) and not failures,
            )
            if authorization_blocked:
                break
        return CollectionResult(collected, added, duplicates, incomplete, tuple(failures))

    def _report(
        self, raw: Any, root_partition: str,
        partition_start: datetime, partition_end: datetime,
    ) -> HistoricalIntelligenceItem | None:
        if not isinstance(raw, dict):
            return None
        fields = raw.get("fields", {})
        if not isinstance(fields, dict):
            return None
        title = str(fields.get("title") or "").strip()
        url = str(fields.get("url") or raw.get("href") or "").strip()
        dates = fields.get("date", {}) if isinstance(fields.get("date"), dict) else {}
        created = _timestamp(dates.get("created"))
        if not title or not url or created is None:
            return None
        if not partition_start <= created < partition_end:
            return None
        timestamp = _iso(created) or ""
        identity = hashlib.sha256(f"ReliefWeb|{raw.get('id')}|{url}".encode("utf-8")).hexdigest()
        country = fields.get("primary_country", {})
        source = fields.get("source")
        return HistoricalIntelligenceItem(
            record_id=identity, title=title, source=self.provider, source_url=url,
            published_at=timestamp, available_at=timestamp,
            source_country=_optional_string(country.get("name"))
            if isinstance(country, dict) else None,
            metadata={
                "historical_provider": self.provider, "query": self.query,
                "root_partition": root_partition,
                "partition_start": partition_start.isoformat(),
                "partition_end": partition_end.isoformat(),
                "availability_timestamp_policy": self.availability_timestamp_policy,
                "reliefweb_id": raw.get("id"), "original_date": dates.get("original"),
                "source": source, "body": fields.get("body"),
            },
        )


def _normalized_story_url(value: str) -> str:
    """Return a stable audit URL without changing the provider's primary identity."""
    try:
        parsed = urlsplit(value.strip())
    except (TypeError, ValueError):
        return str(value or "").strip().lower()
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parsed.path or "/") or "/"
    return f"{host}{path}"


class MediaCloudHistoricalIntelligenceCollector:
    """Collect Media Cloud stories with indexed-time replay availability."""

    provider = "Media Cloud"
    availability_timestamp_policy = "mediacloud.indexed_date"

    def __init__(
        self, store: HistoricalIntelligenceDatasetStore,
        http_get: HttpGet = requests.get, timeout: float = REQUEST_TIMEOUT,
        retries: int = 1, delay_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        window: timedelta = timedelta(days=1), query: str = "geopolitics",
        page_size: int = 1000, api_key: str | None = MEDIA_CLOUD_API_KEY,
        collection_ids: tuple[int, ...] = MEDIA_CLOUD_COLLECTION_IDS,
        checkpoint: CollectionCheckpoint | None = None,
        progress: ProgressCallback | None = None,
        manifest: HistoricalIntelligenceManifestStore | None = None,
        rate_limit_backoff_seconds: float = 60.0,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        if window.total_seconds() <= 0 or not 1 <= page_size <= 1000:
            raise ValueError("invalid Media Cloud collection settings")
        if not api_key:
            raise ValueError("MEDIA_CLOUD_API_KEY is required")
        if not collection_ids:
            raise ValueError("Media Cloud requires at least one collection ID")
        self.store = store
        self.reader = RetryingReader(
            http_get, timeout, retries, delay_seconds, sleep,
            rate_limit_backoff_seconds=rate_limit_backoff_seconds,
            maximum_rate_limit_backoff_seconds=max(120.0, rate_limit_backoff_seconds),
            jitter=jitter,
            headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
            non_retryable_statuses=frozenset({401, 403}),
        )
        self.window = window
        self.query = query
        self.page_size = page_size
        self.collection_ids = collection_ids
        self.checkpoint = checkpoint or CollectionCheckpoint(store.path.parent / "checkpoint.json")
        self.progress = progress
        self.manifest = manifest

    def collect(self, start: datetime, end: datetime) -> CollectionResult:
        start, end = _utc_range(start, end)
        started = time.monotonic()
        state = self.checkpoint.section("intelligence_media_cloud")
        completed = set(state.get("completed_windows", []))
        failures = list(state.get("failures", []))
        pagination_tokens = dict(state.get("pagination_tokens", {}))
        partition_records = dict(state.get("partition_records", {}))
        retry_queue = [
            item for item in state.get("retry_queue", []) if item not in completed
        ]
        windows: list[tuple[datetime, datetime, str]] = []
        cursor = start
        while cursor < end:
            window_end = min(cursor + self.window, end)
            windows.append((cursor, window_end, f"{cursor.isoformat()}..{window_end.isoformat()}"))
            cursor = window_end
        collected = added = duplicates = incomplete = 0
        authorization_blocked = False
        for cursor, window_end, window_key in windows:
            if window_key in completed:
                continue
            if window_key not in retry_queue:
                retry_queue.append(window_key)
            partition_id = HistoricalIntelligenceManifestStore._partition_id(
                self.provider, cursor, window_end,
            )
            if self.manifest is not None:
                self.manifest.update_status(partition_id, "collecting")
            token = pagination_tokens.get(window_key)
            window_records = int(partition_records.get(window_key, 0))
            try:
                while True:
                    params: dict[str, Any] = {
                        "q": self.query,
                        "start": cursor.date().isoformat(),
                        "end": window_end.date().isoformat(),
                        "platform": "onlinenews-mediacloud",
                        "cs": ",".join(str(item) for item in self.collection_ids),
                        "page_size": self.page_size,
                        "sort_order": "asc",
                    }
                    if token:
                        params["pagination_token"] = token
                    payload = self.reader.json(MEDIA_CLOUD_API_URL, params)
                    stories = payload.get("stories", []) if isinstance(payload, dict) else []
                    parsed: list[HistoricalIntelligenceItem] = []
                    for raw in stories if isinstance(stories, list) else []:
                        item = self._story(raw, window_key, cursor, window_end, end)
                        if item is None:
                            incomplete += 1
                        else:
                            parsed.append(item)
                    new, repeated = self.store.upsert(parsed)
                    collected += len(parsed)
                    added += new
                    duplicates += repeated
                    window_records += len(parsed)
                    token = payload.get("pagination_token") if isinstance(payload, dict) else None
                    if token:
                        pagination_tokens[window_key] = str(token)
                    else:
                        pagination_tokens.pop(window_key, None)
                    partition_records[window_key] = window_records
                    self.checkpoint.update(
                        "intelligence_media_cloud",
                        completed_windows=sorted(completed), failures=failures,
                        pagination_tokens=pagination_tokens,
                        partition_records=partition_records,
                        retry_queue=retry_queue, current_window=window_key,
                        windows_total=len(windows), windows_completed=len(completed),
                        cooldown=self.reader.cooldown_state, complete=False,
                    )
                    if not token:
                        break
                completed.add(window_key)
                retry_queue = [item for item in retry_queue if item != window_key]
                failures = [item for item in failures if not item.startswith(
                    f"Media Cloud {window_key}:"
                )]
                if self.manifest is not None:
                    self.manifest.update_status(
                        partition_id, "complete", records=window_records,
                    )
            except RuntimeError as error:
                failure = f"Media Cloud {window_key}: {error}"
                if failure not in failures:
                    failures.append(failure)
                if self.manifest is not None:
                    self.manifest.update_status(
                        partition_id, "failed", pagination_token=token,
                    )
                authorization_blocked = isinstance(error, PublicDataRequestError) and (
                    error.status_code in {401, 403}
                )
            self.checkpoint.update(
                "intelligence_media_cloud",
                completed_windows=sorted(completed), failures=failures,
                pagination_tokens=pagination_tokens,
                partition_records=partition_records,
                retry_queue=retry_queue, current_window=None,
                windows_total=len(windows), windows_completed=len(completed),
                cooldown=self.reader.cooldown_state,
                rate_limit_events_this_run=self.reader.rate_limit_events,
                complete=len(completed) == len(windows) and not failures,
            )
            _emit(
                self.progress, started, stage="intelligence",
                provider=self.provider, windows_completed=len(completed),
                windows_total=len(windows), failed_windows=len(failures),
                retry_queue_size=len(retry_queue),
                remaining_windows=max(0, len(windows) - len(completed)),
                cooldown=self.reader.cooldown_state,
                estimated_remaining_work={
                    "logical_requests_lower_bound": max(0, len(windows) - len(completed)),
                    "minutes_at_normal_pacing": round(
                        max(0, len(windows) - len(completed)) * self.reader.delay_seconds / 60, 1,
                    ),
                },
            )
            if authorization_blocked:
                break
        return CollectionResult(collected, added, duplicates, incomplete, tuple(failures))

    def _story(
        self, raw: Any, root_partition: str,
        partition_start: datetime, partition_end: datetime,
        collection_end: datetime,
    ) -> HistoricalIntelligenceItem | None:
        if not isinstance(raw, dict):
            return None
        story_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        indexed = _timestamp(raw.get("indexed_date"))
        if not story_id or not title or not url or indexed is None or indexed >= collection_end:
            return None
        publish_date = str(raw.get("publish_date") or "").strip() or None
        available_at = _iso(indexed) or ""
        return HistoricalIntelligenceItem(
            record_id=f"mediacloud:{story_id}", title=title,
            source=self.provider, source_url=url,
            # Media Cloud's publication value is heuristic and date-only. Keep
            # it in metadata; replay ordering and visibility use indexed time.
            published_at=available_at,
            available_at=available_at,
            source_domain=_optional_string(raw.get("media_url")),
            language=_optional_string(raw.get("language")),
            metadata={
                "historical_provider": self.provider,
                "media_cloud_story_id": story_id,
                "normalized_url": _normalized_story_url(url),
                "query": self.query,
                "collection_ids": list(self.collection_ids),
                "collection_partition": root_partition,
                "root_partition": root_partition,
                "partition_start": partition_start.isoformat(),
                "partition_end": partition_end.isoformat(),
                "availability_timestamp_policy": self.availability_timestamp_policy,
                "indexed_date": raw.get("indexed_date"),
                "publish_date": publish_date,
                "media_name": raw.get("media_name"),
            },
        )


class MultiProviderHistoricalIntelligenceCollector:
    """Run provider collectors into one deduplicated historical intelligence store."""

    def __init__(
        self, collectors: tuple[Any, ...], manifest: HistoricalIntelligenceManifestStore,
    ) -> None:
        if not collectors:
            raise ValueError("at least one historical intelligence provider is required")
        self.collectors = collectors
        self.manifest = manifest
        self.store = collectors[0].store
        self.checkpoint = collectors[0].checkpoint
        self.window = collectors[0].window

    def collect(self, start: datetime, end: datetime) -> CollectionResult:
        totals = [collector.collect(start, end) for collector in self.collectors]
        return CollectionResult(
            sum(item.collected for item in totals), sum(item.added for item in totals),
            sum(item.duplicates for item in totals), sum(item.incomplete for item in totals),
            tuple(failure for item in totals for failure in item.failures),
        )

    def coverage_by_provider(self) -> dict[str, dict[str, int]]:
        return self.manifest.coverage()


@dataclass(frozen=True)
class DatasetSummary:
    generated_at: str
    start: str
    end: str
    markets_collected: int
    markets_with_valid_price_history: int
    intelligence_records: int
    intelligence_coverage_windows: int
    missing_data: dict[str, int]
    failures: tuple[str, ...]
    validation: DatasetValidation = field(default_factory=DatasetValidation)
    discovered_market_denominator: int = 0
    market_coverage_percentage: float = 0.0
    market_closures_by_month: dict[str, int] = field(default_factory=dict)
    markets_by_actual_close_month: dict[str, int] = field(default_factory=dict)
    markets_by_creation_month: dict[str, int] = field(default_factory=dict)
    markets_excluded_by_reason: dict[str, int] = field(default_factory=dict)
    excluded_markets: int = 0
    dataset_size_bytes: int = 0
    markets_remaining: int = 0
    intelligence_windows_remaining: int = 0
    api_failures: int = 0
    intelligence_records_by_provider: dict[str, int] = field(default_factory=dict)
    intelligence_coverage_by_provider: dict[str, dict[str, int]] = field(default_factory=dict)
    intelligence_coverage_by_provider_day: dict[str, dict[str, str]] = field(default_factory=dict)


class HistoricalDatasetBuilder:
    def __init__(
        self, market_collector: HistoricalMarketCollector,
        intelligence_collector: GDELTIntelligenceCollector,
        summary_path: str | Path,
    ) -> None:
        self.market_collector = market_collector
        self.intelligence_collector = intelligence_collector
        self.summary_path = Path(summary_path)

    def build(self, start: datetime, end: datetime) -> DatasetSummary:
        start, end = _utc_range(start, end)
        self.market_collector.collect(start, end)
        self.intelligence_collector.collect(start, end)
        return self.generate_summary(start, end)

    def generate_summary(self, start: datetime, end: datetime) -> DatasetSummary:
        """Regenerate quality metrics from raw stores and durable checkpoint state."""
        start, end = _utc_range(start, end)
        self.market_collector.store.classify_existing()
        markets = self.market_collector.store.load()
        intelligence = self.intelligence_collector.store.load()
        in_range_markets = [
            item for item in markets
            if start <= (
                _timestamp(item.closed_at) or datetime.min.replace(tzinfo=timezone.utc)
            ) < end
        ]
        in_range_intelligence = [
            item for item in intelligence
            if start <= (_timestamp(item.published_at) or datetime.min.replace(tzinfo=timezone.utc)) < end
        ]
        market_state = self.market_collector.checkpoint.section("markets")
        legacy_exclusions = _legacy_market_exclusions(
            market_state.get("failures", []), market_state.get("market_exclusions", []),
        )
        if legacy_exclusions != market_state.get("market_exclusions", []):
            self.market_collector.checkpoint.update(
                "markets", market_exclusions=legacy_exclusions,
            )
            market_state = self.market_collector.checkpoint.section("markets")
        intelligence_state = self.intelligence_collector.checkpoint.section("intelligence")
        reliefweb_state = self.intelligence_collector.checkpoint.section("intelligence_reliefweb")
        denominator = max(
            int(market_state.get("discovered_market_denominator", 0)),
            len(in_range_markets) + max(
                int(market_state.get("failed_markets", 0)),
                len(market_state.get("market_exclusions", [])),
            ),
        )
        valid_histories = sum(item.has_valid_price_history for item in in_range_markets)
        closures_by_month: dict[str, int] = {}
        actual_closes_by_month: dict[str, int] = {}
        creations_by_month: dict[str, int] = {}
        for market in in_range_markets:
            distribution_time = _timestamp(market.scheduled_end_at) or _timestamp(market.closed_at)
            if distribution_time is not None:
                month = distribution_time.strftime("%Y-%m")
                closures_by_month[month] = closures_by_month.get(month, 0) + 1
            actual_close = _timestamp(market.closed_at)
            if actual_close is not None:
                month = actual_close.strftime("%Y-%m")
                actual_closes_by_month[month] = actual_closes_by_month.get(month, 0) + 1
            created = _timestamp(market.created_at)
            if created is not None:
                month = created.strftime("%Y-%m")
                creations_by_month[month] = creations_by_month.get(month, 0) + 1
        exclusions = [
            item for item in market_state.get("market_exclusions", [])
            if isinstance(item, dict)
        ]
        exclusions_by_reason: dict[str, int] = {}
        for exclusion in exclusions:
            reason = str(exclusion.get("reason") or "unknown")
            exclusions_by_reason[reason] = exclusions_by_reason.get(reason, 0) + 1
        completed_windows = set(intelligence_state.get("completed_windows", []))
        provider_coverage = (
            self.intelligence_collector.coverage_by_provider()
            if hasattr(self.intelligence_collector, "coverage_by_provider") else {}
        )
        collector_manifest = getattr(self.intelligence_collector, "manifest", None)
        provider_days = collector_manifest.coverage_days() if collector_manifest is not None else {}
        effective_completed = min(
            (item.get("complete", 0) for item in provider_coverage.values()),
            default=len(completed_windows),
        )
        records_by_provider: dict[str, int] = {}
        for item in in_range_intelligence:
            provider = str(item.metadata.get("historical_provider") or item.source)
            records_by_provider[provider] = records_by_provider.get(provider, 0) + 1
        expected_windows = max(
            1, int((end - start + self.intelligence_collector.window - timedelta.resolution)
                   / self.intelligence_collector.window),
        )
        summary = DatasetSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            start=start.isoformat(), end=end.isoformat(),
            markets_collected=len(in_range_markets),
            markets_with_valid_price_history=valid_histories,
            intelligence_records=len(in_range_intelligence),
            intelligence_coverage_windows=effective_completed,
            missing_data={
                "incomplete_markets": int(market_state.get("incomplete_markets", 0)),
                "market_discovery_incomplete": int(
                    not market_state.get("discovery_complete", False)
                ),
                "markets_without_price_history": sum(
                    not item.has_valid_price_history for item in in_range_markets
                ),
                "failed_discovered_markets": int(market_state.get("failed_markets", 0)),
                "excluded_markets": len(exclusions),
                "unresolved_markets": sum(item.resolution_outcome is None for item in in_range_markets),
                "incomplete_intelligence": int(intelligence_state.get("incomplete_records", 0)),
                "intelligence_windows_missing": max(0, expected_windows - effective_completed),
            },
            failures=tuple(market_state.get("failures", [])) + tuple(
                intelligence_state.get("failures", [])
            ) + tuple(reliefweb_state.get("failures", [])),
            validation=validate_dataset(
                in_range_markets, in_range_intelligence, start, end,
                self.intelligence_collector.window,
            ),
            discovered_market_denominator=denominator,
            market_coverage_percentage=round(valid_histories / denominator * 100, 2)
            if denominator else 0.0,
            market_closures_by_month=dict(sorted(closures_by_month.items())),
            markets_by_actual_close_month=dict(sorted(actual_closes_by_month.items())),
            markets_by_creation_month=dict(sorted(creations_by_month.items())),
            markets_excluded_by_reason=dict(sorted(exclusions_by_reason.items())),
            excluded_markets=len(exclusions),
            dataset_size_bytes=sum(
                path.stat().st_size for path in {
                    self.market_collector.store.path,
                    self.intelligence_collector.store.path,
                } if path.exists()
            ),
            markets_remaining=max(0, denominator - valid_histories),
            intelligence_windows_remaining=max(0, expected_windows - effective_completed),
            api_failures=len(market_state.get("failures", []))
            + len(intelligence_state.get("failures", []))
            + len(reliefweb_state.get("failures", [])),
            intelligence_records_by_provider=dict(sorted(records_by_provider.items())),
            intelligence_coverage_by_provider=provider_coverage,
            intelligence_coverage_by_provider_day=provider_days,
        )
        _atomic_json(self.summary_path, asdict(summary))
        return summary


def _covered_windows(
    records: list[HistoricalIntelligenceItem], start: datetime,
    end: datetime, window: timedelta,
) -> int:
    indexes = {
        int(((_timestamp(record.published_at) or start) - start) / window)
        for record in records if start <= (_timestamp(record.published_at) or start) <= end
    }
    return len(indexes)


def validate_dataset(
    markets: list[HistoricalMarketRecord], intelligence: list[HistoricalIntelligenceItem],
    start: datetime, end: datetime, intelligence_window: timedelta,
    maximum_candle_gap: timedelta = timedelta(days=2),
) -> DatasetValidation:
    """Return replay-oriented structural and temporal quality checks."""
    market_ids = [item.market_id for item in markets]
    intelligence_ids = [item.record_id for item in intelligence]
    unordered = duplicate_candles = missing_periods = incomplete_outcomes = 0
    invalid_resolutions = 0
    for market in markets:
        if market.resolution_outcome is not None and market.resolution_outcome not in market.outcomes:
            invalid_resolutions += 1
        if set(market.price_history) != {outcome.upper() for outcome in market.outcomes}:
            incomplete_outcomes += 1
        market_missing = False
        market_unordered = False
        market_duplicates = False
        for outcome in market.outcomes:
            candles = market.price_history.get(outcome.upper(), ())
            timestamps = [_timestamp(candle.timestamp) for candle in candles]
            valid = [value for value in timestamps if value is not None]
            if valid != sorted(valid):
                market_unordered = True
            if len(valid) != len(set(valid)):
                market_duplicates = True
            if len(valid) < 2 or any(
                right - left > maximum_candle_gap
                for left, right in zip(sorted(valid), sorted(valid)[1:])
            ):
                market_missing = True
        unordered += market_unordered
        duplicate_candles += market_duplicates
        missing_periods += market_missing
    expected = max(1, int((end - start + intelligence_window - timedelta.resolution) / intelligence_window))
    covered = _covered_windows(intelligence, start, end, intelligence_window)
    expected_months = _months_in_range(start, end - timedelta.resolution)
    covered_months = tuple(sorted({
        distribution_time.strftime("%Y-%m") for market in markets
        if (distribution_time := (
            _timestamp(market.scheduled_end_at) or _timestamp(market.closed_at)
        )) is not None and start <= distribution_time <= end
    }))
    actual_close_months = tuple(sorted({
        closed.strftime("%Y-%m") for market in markets
        if (closed := _timestamp(market.closed_at)) is not None and start <= closed <= end
    }))
    creation_months = tuple(sorted({
        created.strftime("%Y-%m") for market in markets
        if (created := _timestamp(market.created_at)) is not None and start <= created <= end
    }))
    missing_actual_close_months = tuple(
        month for month in expected_months if month not in actual_close_months
    )
    return DatasetValidation(
        duplicate_markets=len(market_ids) - len(set(market_ids)),
        duplicate_intelligence=len(intelligence_ids) - len(set(intelligence_ids)),
        markets_with_unordered_candles=unordered,
        markets_with_duplicate_candles=duplicate_candles,
        markets_with_missing_periods=missing_periods,
        incomplete_outcomes=incomplete_outcomes,
        intelligence_windows_expected=expected,
        intelligence_windows_covered=covered,
        intelligence_windows_missing=max(0, expected - covered),
        resolved_markets=sum(item.resolution_outcome is not None for item in markets),
        unresolved_markets=sum(item.resolution_outcome is None for item in markets),
        invalid_resolution_outcomes=invalid_resolutions,
        markets_closed_before_scheduled_end=sum(
            bool(
                _timestamp(item.scheduled_end_at)
                and (_timestamp(item.closed_at) or end) < (_timestamp(item.scheduled_end_at) or start)
            )
            for item in markets
        ),
        market_months_covered=covered_months,
        market_months_missing=tuple(month for month in expected_months if month not in covered_months),
        actual_close_months_covered=actual_close_months,
        actual_close_months_missing=missing_actual_close_months,
        creation_months_covered=creation_months,
        requested_period_covered=not missing_actual_close_months,
    )


def _months_in_range(start: datetime, end: datetime) -> tuple[str, ...]:
    cursor = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
    months: list[str] = []
    while cursor <= end:
        months.append(cursor.strftime("%Y-%m"))
        cursor = datetime(
            cursor.year + int(cursor.month == 12), cursor.month % 12 + 1, 1,
            tzinfo=timezone.utc,
        )
    return tuple(months)


def _monthly_windows(start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], ...]:
    """Small scheduled-end partitions avoid Gamma failures on broad date ranges."""
    cursor = start
    windows: list[tuple[datetime, datetime]] = []
    while cursor < end:
        next_month = datetime(
            cursor.year + int(cursor.month == 12), cursor.month % 12 + 1, 1,
            tzinfo=timezone.utc,
        )
        window_end = min(next_month, end)
        windows.append((cursor, window_end))
        cursor = window_end
    return tuple(windows)


def _market_category(raw: dict[str, Any]) -> str:
    supplied = str(raw.get("category") or "").strip().upper()
    if supplied and supplied != "OTHER":
        return supplied
    classified = MarketClassifier().classify({"question": str(raw.get("question") or "")})
    return classified.event_type.name


@dataclass(frozen=True)
class ReplayDataset:
    snapshots: tuple[HistoricalMarketSnapshot, ...]
    intelligence: tuple[HistoricalIntelligenceRecord, ...]
    skipped_markets: int = 0
    skipped_intelligence: int = 0

    def replay_engine(self) -> HistoricalReplayEngine:
        """Build the unchanged replay engine with converted historical intelligence."""
        return HistoricalReplayEngine(list(self.intelligence))


class HistoricalDatasetReplayAdapter:
    """Convert collected raw records into leakage-safe replay engine inputs."""

    def convert(
        self,
        markets: list[HistoricalMarketRecord],
        intelligence: list[HistoricalIntelligenceItem],
    ) -> ReplayDataset:
        snapshots: list[HistoricalMarketSnapshot] = []
        skipped_markets = 0
        for market in markets:
            closed = _timestamp(market.closed_at)
            yes_history = market.price_history.get("YES", ())
            if closed is None or not yes_history:
                skipped_markets += 1
                continue
            resolved_yes = None
            if market.resolution_outcome is not None:
                resolved_yes = market.resolution_outcome.upper() == "YES"
            for candle in yes_history:
                observed = _timestamp(candle.timestamp)
                if observed is None or observed >= closed:
                    continue
                snapshots.append(HistoricalMarketSnapshot(
                    market_id=market.market_id, question=market.question,
                    observed_at=observed.isoformat(), yes_price=candle.price,
                    resolved_yes=resolved_yes,
                    resolved_at=closed.isoformat() if resolved_yes is not None else None,
                    liquidity=market.liquidity, volume=market.volume,
                    category=market.category if market.category != "OTHER" else _market_category(
                        {"question": market.question}
                    ),
                ))
        replay_intelligence: list[HistoricalIntelligenceRecord] = []
        skipped_intelligence = 0
        for item in intelligence:
            try:
                replay_intelligence.append(HistoricalIntelligenceRecord(
                    title=item.title,
                    summary=str(item.metadata.get("summary") or item.title),
                    source=item.source, source_url=item.source_url,
                    published_at=item.published_at, available_at=item.available_at,
                    category=str(item.metadata.get("category") or "OTHER"),
                    country=item.source_country,
                ))
            except (TypeError, ValueError):
                skipped_intelligence += 1
        snapshots.sort(key=lambda item: (_timestamp(item.observed_at), item.market_id))
        replay_intelligence.sort(key=lambda item: _timestamp(item.published_at))
        return ReplayDataset(
            tuple(snapshots), tuple(replay_intelligence),
            skipped_markets, skipped_intelligence,
        )


def _classify_clob_failure(
    raw: dict[str, Any], market_id: str, outcome: str, token: str,
    error: PublicDataRequestError,
) -> MarketExclusion:
    """Classify a CLOB failure only from persisted market/API evidence."""
    detail = (error.response_body or str(error)).strip()
    normalized = detail.lower()
    resolution_status = str(raw.get("umaResolutionStatus") or "").lower()
    if "invalid token" in normalized:
        reason = "invalid_token"
    elif any(term in normalized for term in (
        "invalid filter", "invalid timestamp", "startts", "endts", "interval is too long",
    )):
        reason = "invalid_timestamps"
    elif "cancel" in resolution_status or "cancel" in normalized:
        reason = "cancelled_market"
    elif "expir" in normalized:
        reason = "expired_market"
    elif error.status_code == 404 or "not found" in normalized or "no history" in normalized:
        reason = "unavailable_history"
    else:
        reason = "api_network_failure"
    return MarketExclusion(
        market_id=market_id, reason=reason,
        detail=detail or "CLOB price-history request failed",
        outcome=outcome, token_id=token, status_code=error.status_code,
    )


def _legacy_market_exclusions(
    failures: Any, existing: Any,
) -> list[dict[str, Any]]:
    """Migrate provably oversized legacy CLOB requests into structured exclusions."""
    exclusions = {
        str(item.get("market_id")): item
        for item in existing if isinstance(item, dict) and item.get("market_id")
    } if isinstance(existing, list) else {}
    for failure in failures if isinstance(failures, list) else []:
        match = re.search(
            r"market ([^:]+):.*400 Client Error.*startTs=(\d+).*endTs=(\d+)",
            str(failure),
        )
        if not match:
            continue
        market_id, start_value, end_value = match.groups()
        if int(end_value) - int(start_value) <= 7 * 86400:
            continue
        exclusions.setdefault(market_id, asdict(MarketExclusion(
            market_id=market_id, reason="invalid_timestamps",
            detail="legacy CLOB request interval exceeded the accepted range",
            status_code=400,
        )))
    return list(exclusions.values())


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _utc_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("dataset timestamps must be timezone-aware")
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if start >= end:
        raise ValueError("start must be earlier than end")
    return start, end


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.1 * (2 ** attempt))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a historical replay dataset")
    parser.add_argument("--start", help="ISO-8601 start; defaults to six months ago")
    parser.add_argument("--end", help="ISO-8601 end; defaults to now")
    parser.add_argument("--output-dir", default="data/historical_dataset")
    parser.add_argument("--gdelt-query", default="geopolitics")
    parser.add_argument("--media-cloud-query", default="geopolitics")
    parser.add_argument(
        "--include-media-cloud", action="store_true",
        help="include Media Cloud in a newly frozen historical intelligence plan",
    )
    parser.add_argument(
        "--pilot-manifest",
        help="frozen event-focused pilot manifest; requires a separate output directory",
    )
    parser.add_argument(
        "--metadata-only", action="store_true",
        help="discover and persist the selected market universe without price or intelligence calls",
    )
    parser.add_argument("--max-metadata-pages", type=int)
    parser.add_argument("--refresh-selection", action="store_true")
    parser.add_argument(
        "--universe-report-only", action="store_true",
        help="regenerate clustering and sparse-month analysis from selected metadata",
    )
    parser.add_argument(
        "--freeze-manifest", action="store_true",
        help="freeze the selected universe for resumable downstream collection",
    )
    parser.add_argument(
        "--summary-only", action="store_true",
        help="regenerate summary and category metadata from existing raw files",
    )
    parser.add_argument(
        "--intelligence-status", action="store_true",
        help="print provider/day intelligence coverage without making network requests",
    )
    parser.add_argument(
        "--intelligence-only", action="store_true",
        help="collect only frozen historical intelligence partitions (useful for pilots/resume)",
    )
    args = parser.parse_args()
    pilot: dict[str, Any] | None = None
    if args.pilot_manifest:
        try:
            pilot = load_event_focused_pilot_manifest(args.pilot_manifest)
        except ValueError as error:
            parser.error(str(error))
        if not (args.intelligence_only or args.intelligence_status):
            parser.error("--pilot-manifest is limited to intelligence collection/status")
        if args.output_dir == parser.get_default("output_dir"):
            parser.error("--pilot-manifest requires an explicit separate --output-dir")
    output = Path(args.output_dir)
    if pilot is not None and output.resolve() == Path(pilot["_manifest_path"]).parent:
        parser.error("pilot outputs must not be stored in the frozen main dataset directory")
    run_lock = CollectionRunLock(output / "collection.lock")
    try:
        run_lock.acquire()
    except RuntimeError as error:
        parser.error(str(error))
    atexit.register(run_lock.release)
    checkpoint = CollectionCheckpoint(output / "checkpoint.json")
    saved_run = checkpoint.section("run")
    resume_default = not args.start and not args.end and saved_run.get("complete") is False
    if pilot is not None:
        start = _timestamp(pilot["_collection_start"])
        end = _timestamp(pilot["_collection_end"])
        supplied_start, supplied_end = _timestamp(args.start), _timestamp(args.end)
        if (args.start and supplied_start != start) or (args.end and supplied_end != end):
            parser.error("pilot collection timestamps are frozen by --pilot-manifest")
        try:
            freeze_pilot_collection_reference(pilot, output / "pilot_collection_plan.json")
        except ValueError as error:
            parser.error(str(error))
    else:
        end = _timestamp(saved_run.get("end")) if resume_default else (
            _timestamp(args.end) if args.end else datetime.now(timezone.utc)
        )
        start = _timestamp(saved_run.get("start")) if resume_default else (
            _timestamp(args.start) if args.start else end - timedelta(days=183) if end else None
        )
    if start is None or end is None:
        parser.error("--start and --end must be valid ISO-8601 timestamps")
    def report(progress: dict[str, Any]) -> None:
        if progress.get("stage") == "market_discovery":
            print(f"Market discovery: {progress['markets_discovered']} found | "
                  f"elapsed {progress['elapsed_seconds']:.1f}s", flush=True)
        elif progress.get("stage") == "market_selection":
            print(
                f"Metadata: {progress['pages_scanned']} pages | "
                f"scanned {progress['markets_scanned']} | "
                f"actual-close candidates {progress['markets_discovered']} | "
                f"selected {progress['markets_selected']} | "
                f"elapsed {progress['elapsed_seconds']:.1f}s", flush=True,
            )
        elif progress.get("stage") == "markets":
            print(
                f"Markets: {progress['markets_processed']}/{progress['markets_total']} | "
                f"remaining {progress.get('markets_remaining', 0)} | "
                f"price histories {progress['successful_price_histories']} | "
                f"coverage {progress.get('price_coverage_percentage', 0.0):.2f}% | "
                f"failed {progress['failed_markets']} | elapsed {progress['elapsed_seconds']:.1f}s",
                flush=True,
            )
        else:
            cooldown = progress.get("cooldown", {})
            estimate = progress.get("estimated_remaining_work", {})
            print(
                f"Intelligence windows: {progress['windows_completed']}/{progress['windows_total']} | "
                f"failed {progress.get('failed_windows', 0)} | "
                f"queued {progress.get('retry_queue_size', 0)} | "
                f"remaining {progress.get('remaining_windows', 0)} | "
                f"cooldown {cooldown.get('remaining_seconds', 0):.1f}s | "
                f"estimated {estimate.get('logical_requests_lower_bound', 0)} requests/"
                f"{estimate.get('minutes_at_normal_pacing', 0):.1f} min | "
                f"elapsed {progress['elapsed_seconds']:.1f}s", flush=True,
            )

    market_store = HistoricalMarketDatasetStore(output / "markets.json")
    intelligence_store = HistoricalIntelligenceDatasetStore(output / "intelligence.json")
    intelligence_manifest = HistoricalIntelligenceManifestStore(
        output / "intelligence_manifest.json",
    )
    universe_store = HistoricalMarketUniverseStore(output / "selected_markets.json")
    manifest_store = CollectionManifestStore(output / "collection_manifest.json")
    if args.intelligence_status:
        try:
            status = pilot_intelligence_status_report(
                pilot, intelligence_manifest, intelligence_store, checkpoint,
            ) if pilot is not None else historical_intelligence_status_report(
                intelligence_manifest, intelligence_store, checkpoint,
            )
        except ValueError as error:
            parser.error(str(error))
        print(json.dumps(status, indent=2))
        return
    selector = HistoricalMarketSelector(
        universe_store,
        checkpoint=checkpoint, progress=report,
    )
    if args.universe_report_only:
        quality = analyze_market_universe(
            universe_store.load(), _months_in_range(start, end - timedelta.resolution),
        )
        universe_store.save_quality_report(quality)
        print(json.dumps(asdict(quality), indent=2))
        return
    if args.freeze_manifest:
        manifest = manifest_store.create(universe_store, start, end)
        manifest_store.validate(universe_store)
        print(json.dumps(asdict(manifest), indent=2))
        return
    if args.metadata_only:
        selected, selection_report = selector.select(
            start, end, max_pages=args.max_metadata_pages,
            refresh=args.refresh_selection,
        )
        quality = analyze_market_universe(
            selected, _months_in_range(start, end - timedelta.resolution),
        )
        universe_store.save_quality_report(quality)
        print(json.dumps({
            "selection_report": asdict(selection_report),
            "quality_report": asdict(quality),
        }, indent=2))
        return
    provider_specs = [
        HistoricalIntelligenceProviderSpec(
            "GDELT", args.gdelt_query, "gdelt.seendate_first_observed",
        ),
        HistoricalIntelligenceProviderSpec(
            "ReliefWeb", "", "reliefweb.date.created",
        ),
    ]
    if args.include_media_cloud:
        provider_specs.append(HistoricalIntelligenceProviderSpec(
            "Media Cloud", args.media_cloud_query, "mediacloud.indexed_date",
        ))
    intelligence_manifest.create(start, end, tuple(provider_specs))
    gdelt_collector = GDELTIntelligenceCollector(
        intelligence_store, query=args.gdelt_query,
        checkpoint=checkpoint, progress=report,
        retries=1, delay_seconds=GDELT_REQUEST_DELAY_MIN_SECONDS,
        maximum_delay_seconds=GDELT_REQUEST_DELAY_MAX_SECONDS,
        max_consecutive_failures=30,
        rate_limit_backoff_seconds=GDELT_COOLDOWN_MIN_SECONDS,
        maximum_rate_limit_backoff_seconds=GDELT_COOLDOWN_MAX_SECONDS,
        manifest=intelligence_manifest,
    )
    reliefweb_collector = ReliefWebHistoricalIntelligenceCollector(
        intelligence_store, checkpoint=checkpoint, progress=report,
        manifest=intelligence_manifest,
    )
    media_cloud_collector = MediaCloudHistoricalIntelligenceCollector(
        intelligence_store, query=args.media_cloud_query,
        checkpoint=checkpoint, progress=report,
        manifest=intelligence_manifest,
    ) if args.include_media_cloud else None
    # A pilot must expose provider-specific blockers promptly. Running ReliefWeb
    # first prevents a long, rate-limited GDELT resume from indefinitely hiding
    # missing ReliefWeb authorization; both providers still share one day plan.
    provider_collectors = list(
        (reliefweb_collector, gdelt_collector) if pilot is not None
        else (gdelt_collector, reliefweb_collector)
    )
    if media_cloud_collector is not None:
        provider_collectors.insert(1 if pilot is not None else len(provider_collectors),
                                   media_cloud_collector)
    intelligence_collector = MultiProviderHistoricalIntelligenceCollector(
        tuple(provider_collectors), intelligence_manifest,
    )
    if args.intelligence_only:
        intelligence_collector.collect(start, end)
        status = pilot_intelligence_status_report(
            pilot, intelligence_manifest, intelligence_store, checkpoint,
        ) if pilot is not None else historical_intelligence_status_report(
            intelligence_manifest, intelligence_store, checkpoint,
        )
        print(json.dumps(status, indent=2))
        return
    builder = HistoricalDatasetBuilder(
        HistoricalMarketCollector(
            market_store, checkpoint=checkpoint, progress=report,
            manifest=manifest_store, universe=universe_store,
        ),
        intelligence_collector,
        output / "summary.json",
    )
    if args.summary_only:
        summary = builder.generate_summary(start, end)
        print(json.dumps(asdict(summary), indent=2))
        return
    checkpoint.update("run", start=start.isoformat(), end=end.isoformat(), complete=False)
    summary = builder.build(start, end)
    final_state = checkpoint.load()
    collection_complete = all(
        isinstance(final_state.get(section), dict)
        and final_state[section].get("complete") is True
        for section in ("markets", "intelligence", "intelligence_reliefweb")
    )
    checkpoint.update(
        "run", start=start.isoformat(), end=end.isoformat(), complete=collection_complete,
    )
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
