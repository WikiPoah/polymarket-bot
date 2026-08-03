"""Read-only collectors for reproducible historical backtest datasets."""

from __future__ import annotations

import argparse
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable, Generic, TypeVar

import requests

from src.config import INTELLIGENCE_USER_AGENT, REQUEST_TIMEOUT
from src.coverage_probe import (
    CLOB_HISTORY_URL,
    GAMMA_MARKETS_URL,
    GDELT_DOC_URL,
    HistoricalCoverageProbe,
    _iso,
    _items,
    _timestamp,
)


HttpGet = Callable[..., Any]
T = TypeVar("T")
ProgressCallback = Callable[[dict[str, Any]], None]


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

    def __post_init__(self) -> None:
        if not self.market_id or not self.question or len(self.outcomes) < 2:
            raise ValueError("incomplete historical market")
        if _timestamp(self.created_at) is None or _timestamp(self.closed_at) is None:
            raise ValueError("invalid market timestamps")

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
    )


def _intelligence_decoder(value: dict[str, Any]) -> HistoricalIntelligenceItem:
    return HistoricalIntelligenceItem(**value)


class HistoricalMarketDatasetStore(VersionedJsonStore[HistoricalMarketRecord]):
    def __init__(self, path: str | Path) -> None:
        super().__init__(path, _market_decoder, lambda item: item.market_id)


class HistoricalIntelligenceDatasetStore(VersionedJsonStore[HistoricalIntelligenceItem]):
    def __init__(self, path: str | Path) -> None:
        super().__init__(path, _intelligence_decoder, lambda item: item.record_id)


@dataclass(frozen=True)
class CollectionResult:
    collected: int
    added: int
    duplicates: int
    incomplete: int
    failures: tuple[str, ...]


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


def _emit(callback: ProgressCallback | None, started: float, **values: Any) -> None:
    if callback is not None:
        callback({**values, "elapsed_seconds": round(time.monotonic() - started, 1)})


class RetryingReader:
    """Small retry/rate-limit boundary shared by public collectors."""

    def __init__(
        self, http_get: HttpGet, timeout: float, retries: int,
        delay_seconds: float, sleep: Callable[[float], None],
    ) -> None:
        if retries < 0 or delay_seconds < 0:
            raise ValueError("retry and delay settings cannot be negative")
        self.http_get = http_get
        self.timeout = timeout
        self.retries = retries
        self.delay_seconds = delay_seconds
        self.sleep = sleep
        self.headers = {"User-Agent": INTELLIGENCE_USER_AGENT}
        self._throttle_lock = threading.Lock()
        self._next_request_at = 0.0

    def json(self, url: str, params: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            response: Any = None
            try:
                with self._throttle_lock:
                    wait = max(0.0, self._next_request_at - time.monotonic())
                    if wait:
                        self.sleep(wait)
                    self._next_request_at = time.monotonic() + self.delay_seconds
                response = self.http_get(
                    url, params=params, headers=self.headers, timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError, TypeError) as error:
                last_error = error
                if attempt < self.retries:
                    error_response = getattr(error, "response", None) or response
                    status = getattr(error_response, "status_code", None)
                    headers = getattr(error_response, "headers", {}) or {}
                    try:
                        retry_after = float(headers.get("Retry-After", 0))
                    except (TypeError, ValueError):
                        retry_after = 0.0
                    backoff = self.delay_seconds * (2 ** attempt)
                    if status == 429:
                        backoff = max(5.0, backoff, retry_after)
                    self.sleep(backoff)
        raise RuntimeError(str(last_error or "public data request failed")) from last_error

    def rate_limit(self) -> None:
        """Compatibility hook; request starts are throttled in ``json``."""


class HistoricalMarketCollector:
    """Collect closed Gamma markets and their public CLOB candle histories."""

    def __init__(
        self, store: HistoricalMarketDatasetStore,
        http_get: HttpGet = requests.get, timeout: float = REQUEST_TIMEOUT,
        retries: int = 2, delay_seconds: float = 0.1,
        sleep: Callable[[float], None] = time.sleep, page_size: int = 100,
        checkpoint_size: int = 1, workers: int = 4,
        checkpoint: CollectionCheckpoint | None = None,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.store = store
        self.reader = RetryingReader(http_get, timeout, retries, delay_seconds, sleep)
        self.page_size = page_size
        self.checkpoint_size = max(1, checkpoint_size)
        self.workers = max(1, workers)
        self.checkpoint = checkpoint or CollectionCheckpoint(store.path.parent / "checkpoint.json")
        self.progress = progress

    def collect(self, start: datetime, end: datetime, max_pages: int | None = None) -> CollectionResult:
        start, end = _utc_range(start, end)
        started = time.monotonic()
        existing = {item.market_id: item for item in self.store.load()}
        state = self.checkpoint.section("markets")
        failures = list(state.get("failures", []))
        candidates: list[dict[str, Any]] = []
        incomplete = 0
        offset = 0
        pages = 0
        finished = False
        discovery_complete = True
        while not finished and (max_pages is None or pages < max_pages):
            try:
                payload = self.reader.json(GAMMA_MARKETS_URL, {
                    "closed": "true", "limit": self.page_size, "offset": offset,
                    "order": "closedTime", "ascending": "false",
                })
            except RuntimeError as error:
                failure = f"Gamma page {pages + 1}: {error}"
                if failure not in failures:
                    failures.append(failure)
                discovery_complete = False
                break
            markets = payload if isinstance(payload, list) else []
            if not markets:
                break
            pages += 1
            for raw in markets:
                if not isinstance(raw, dict):
                    incomplete += 1
                    continue
                closed = _timestamp(raw.get("closedTime") or raw.get("endDate"))
                if closed is None:
                    incomplete += 1
                    continue
                if closed < start:
                    finished = True
                    continue
                if closed > end:
                    continue
                candidates.append(raw)
            if len(markets) < self.page_size:
                break
            offset += self.page_size
            self.reader.rate_limit()
            _emit(self.progress, started, stage="market_discovery", markets_discovered=len(candidates))

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
              markets_total=total, successful_price_histories=successful, failed_markets=failed)

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
                failed_markets=failed, complete=False,
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
                    except ValueError:
                        incomplete += 1
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
                            failed_markets=failed, complete=False,
                        )
                    _emit(self.progress, started, stage="markets", markets_processed=processed,
                          markets_total=total, successful_price_histories=successful,
                          failed_markets=failed)
        finally:
            flush()
        self.checkpoint.update(
            "markets", failures=failures, markets_processed=processed,
            markets_total=total, successful_price_histories=successful,
            failed_markets=failed, complete=discovery_complete and processed == total,
        )
        return CollectionResult(successful, added, duplicates, incomplete, tuple(failures))

    def _market(self, raw: dict[str, Any]) -> HistoricalMarketRecord:
        market_id = str(raw.get("id") or raw.get("conditionId") or "")
        question = str(raw.get("question") or "")
        created = _timestamp(raw.get("createdAt") or raw.get("creationDate"))
        closed = _timestamp(raw.get("closedTime") or raw.get("endDate"))
        outcomes = tuple(str(item) for item in _items(raw.get("outcomes")))
        token_values = [str(item) for item in _items(raw.get("clobTokenIds"))]
        if not market_id or not question or created is None or closed is None or len(outcomes) < 2:
            raise ValueError("incomplete market metadata")
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
            payload = self.reader.json(CLOB_HISTORY_URL, {
                "market": token, "startTs": int(created.timestamp()),
                "endTs": int((closed + timedelta(days=1)).timestamp()),
                "fidelity": 60,
            })
            raw_history = payload.get("history", []) if isinstance(payload, dict) else []
            candles: dict[str, PriceCandle] = {}
            for point in raw_history:
                timestamp = _timestamp(point.get("t")) if isinstance(point, dict) else None
                try:
                    price = float(point.get("p")) if isinstance(point, dict) else -1.0
                    candle = PriceCandle(_iso(timestamp) or "", price)
                except (TypeError, ValueError):
                    continue
                candles[candle.timestamp] = candle
            histories[outcome] = tuple(candles[key] for key in sorted(candles))
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
            category=str(raw.get("category") or "OTHER"),
        )


class GDELTIntelligenceCollector:
    """Collect timestamped GDELT articles in bounded, retryable windows."""

    def __init__(
        self, store: HistoricalIntelligenceDatasetStore,
        http_get: HttpGet = requests.get, timeout: float = REQUEST_TIMEOUT,
        retries: int = 2, delay_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        window: timedelta = timedelta(days=1), query: str = "geopolitics",
        checkpoint: CollectionCheckpoint | None = None,
        progress: ProgressCallback | None = None,
        max_consecutive_failures: int = 3,
    ) -> None:
        if window.total_seconds() <= 0:
            raise ValueError("window must be positive")
        self.store = store
        self.reader = RetryingReader(http_get, timeout, retries, delay_seconds, sleep)
        self.window = window
        self.query = query
        self.checkpoint = checkpoint or CollectionCheckpoint(store.path.parent / "checkpoint.json")
        self.progress = progress
        self.max_consecutive_failures = max(1, max_consecutive_failures)

    def collect(self, start: datetime, end: datetime) -> CollectionResult:
        start, end = _utc_range(start, end)
        started = time.monotonic()
        state = self.checkpoint.section("intelligence")
        completed = set(state.get("completed_windows", []))
        failures = list(state.get("failures", []))
        incomplete = 0
        cursor = start
        total_windows = max(1, int((end - start + self.window - timedelta.resolution) / self.window))
        windows_attempted = 0
        consecutive_failures = 0
        collected = 0
        added = 0
        duplicates = 0
        while cursor < end:
            window_end = min(cursor + self.window, end)
            window_key = f"{cursor.isoformat()}..{window_end.isoformat()}"
            if window_key in completed:
                cursor = window_end
                _emit(self.progress, started, stage="intelligence", windows_completed=len(completed),
                      windows_total=total_windows)
                continue
            records: list[HistoricalIntelligenceItem] = []
            try:
                payload = self.reader.json(GDELT_DOC_URL, {
                    "query": self.query, "mode": "ArtList", "format": "json",
                    "maxrecords": 250,
                    "startdatetime": cursor.strftime("%Y%m%d%H%M%S"),
                    "enddatetime": window_end.strftime("%Y%m%d%H%M%S"),
                })
                articles = payload.get("articles", []) if isinstance(payload, dict) else []
                for article in articles:
                    item = self._article(article)
                    if item is None:
                        incomplete += 1
                    elif cursor <= (_timestamp(item.published_at) or end) < window_end:
                        records.append(item)
                new, repeated = self.store.upsert(records)
                collected += len(records)
                added += new
                duplicates += repeated
                completed.add(window_key)
                failures = [item for item in failures if not item.startswith(f"GDELT {window_key}:")]
                consecutive_failures = 0
            except RuntimeError as error:
                failure = f"GDELT {window_key}: {error}"
                if failure not in failures:
                    failures.append(failure)
                consecutive_failures += 1
            windows_attempted += 1
            self.checkpoint.update(
                "intelligence", completed_windows=sorted(completed), failures=failures,
                windows_completed=len(completed), windows_attempted=windows_attempted,
                windows_total=total_windows,
                complete=False,
            )
            _emit(self.progress, started, stage="intelligence", windows_completed=len(completed),
                  windows_total=total_windows, failed_windows=len(failures))
            cursor = window_end
            if consecutive_failures >= self.max_consecutive_failures:
                break
            self.reader.rate_limit()
        self.checkpoint.update(
            "intelligence", completed_windows=sorted(completed), failures=failures,
            windows_completed=len(completed), windows_attempted=windows_attempted,
            windows_total=total_windows,
            complete=len(completed) == total_windows and not failures,
        )
        return CollectionResult(collected, added, duplicates, incomplete, tuple(failures))

    @staticmethod
    def _article(raw: Any) -> HistoricalIntelligenceItem | None:
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
            },
        )


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
        market_result = self.market_collector.collect(start, end)
        intelligence_result = self.intelligence_collector.collect(start, end)
        markets = self.market_collector.store.load()
        intelligence = self.intelligence_collector.store.load()
        in_range_markets = [
            item for item in markets
            if start <= (_timestamp(item.closed_at) or datetime.min.replace(tzinfo=timezone.utc)) <= end
        ]
        in_range_intelligence = [
            item for item in intelligence
            if start <= (_timestamp(item.published_at) or datetime.min.replace(tzinfo=timezone.utc)) <= end
        ]
        summary = DatasetSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            start=start.isoformat(), end=end.isoformat(),
            markets_collected=len(in_range_markets),
            markets_with_valid_price_history=sum(item.has_valid_price_history for item in in_range_markets),
            intelligence_records=len(in_range_intelligence),
            intelligence_coverage_windows=_covered_windows(
                in_range_intelligence, start, end, self.intelligence_collector.window,
            ),
            missing_data={
                "incomplete_markets": market_result.incomplete,
                "market_discovery_incomplete": int(
                    not self.market_collector.checkpoint.section("markets").get("complete", False)
                ),
                "markets_without_price_history": sum(
                    not item.has_valid_price_history for item in in_range_markets
                ),
                "incomplete_intelligence": intelligence_result.incomplete,
                "intelligence_windows_missing": max(
                    0,
                    int((end - start + self.intelligence_collector.window - timedelta.resolution)
                        / self.intelligence_collector.window)
                    - _covered_windows(
                        in_range_intelligence, start, end,
                        self.intelligence_collector.window,
                    ),
                ),
            },
            failures=market_result.failures + intelligence_result.failures,
            validation=validate_dataset(
                in_range_markets, in_range_intelligence, start, end,
                self.intelligence_collector.window,
            ),
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
    for market in markets:
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
    )


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
    args = parser.parse_args()
    output = Path(args.output_dir)
    run_lock = CollectionRunLock(output / "collection.lock")
    try:
        run_lock.acquire()
    except RuntimeError as error:
        parser.error(str(error))
    atexit.register(run_lock.release)
    checkpoint = CollectionCheckpoint(output / "checkpoint.json")
    saved_run = checkpoint.section("run")
    resume_default = not args.start and not args.end and saved_run.get("complete") is False
    end = _timestamp(saved_run.get("end")) if resume_default else (
        _timestamp(args.end) if args.end else datetime.now(timezone.utc)
    )
    start = _timestamp(saved_run.get("start")) if resume_default else (
        _timestamp(args.start) if args.start else end - timedelta(days=183) if end else None
    )
    if start is None or end is None:
        parser.error("--start and --end must be valid ISO-8601 timestamps")
    checkpoint.update("run", start=start.isoformat(), end=end.isoformat(), complete=False)

    def report(progress: dict[str, Any]) -> None:
        if progress.get("stage") == "market_discovery":
            print(f"Market discovery: {progress['markets_discovered']} found | "
                  f"elapsed {progress['elapsed_seconds']:.1f}s", flush=True)
        elif progress.get("stage") == "markets":
            print(
                f"Markets: {progress['markets_processed']}/{progress['markets_total']} | "
                f"price histories {progress['successful_price_histories']} | "
                f"failed {progress['failed_markets']} | elapsed {progress['elapsed_seconds']:.1f}s",
                flush=True,
            )
        else:
            print(
                f"Intelligence windows: {progress['windows_completed']}/{progress['windows_total']} | "
                f"failed {progress.get('failed_windows', 0)} | "
                f"elapsed {progress['elapsed_seconds']:.1f}s", flush=True,
            )

    market_store = HistoricalMarketDatasetStore(output / "markets.json")
    intelligence_store = HistoricalIntelligenceDatasetStore(output / "intelligence.json")
    builder = HistoricalDatasetBuilder(
        HistoricalMarketCollector(market_store, checkpoint=checkpoint, progress=report),
        GDELTIntelligenceCollector(
            intelligence_store, query=args.gdelt_query,
            checkpoint=checkpoint, progress=report,
        ),
        output / "summary.json",
    )
    summary = builder.build(start, end)
    final_state = checkpoint.load()
    collection_complete = all(
        isinstance(final_state.get(section), dict)
        and final_state[section].get("complete") is True
        for section in ("markets", "intelligence")
    )
    checkpoint.update(
        "run", start=start.isoformat(), end=end.isoformat(), complete=collection_complete,
    )
    print(json.dumps(asdict(summary), indent=2))


if __name__ == "__main__":
    main()
