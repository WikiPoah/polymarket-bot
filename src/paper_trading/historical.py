# File-Version: 1.4.0
"""Timestamped market/intelligence storage and leakage-safe historical replay."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.intelligence.client import IntelligenceClient
from src.intelligence.providers.base import IntelligenceProvider
from src.models import GeoPoliticalEvent
from src.paper_trading.analytics import AnalyticsReport, AnalyticsSummary, PerformanceAnalytics
from src.paper_trading.backtesting import BacktestEngine
from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision
from src.persistence import PersistenceCorruptionError
from src.strategy.engine import StrategyDecision
from src.strategy.expected_value import StrategyAction


if TYPE_CHECKING:
    from src.intelligence.pipeline import IntelligencePipeline


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class HistoricalMarketSnapshot:
    market_id: str
    question: str
    observed_at: str
    yes_price: float
    resolved_yes: bool | None = None
    resolved_at: str | None = None
    liquidity: float | None = None
    volume: float | None = None
    category: str = "OTHER"

    def __post_init__(self) -> None:
        if not self.market_id or not self.question:
            raise ValueError("historical market identity is required")
        _parse_time(self.observed_at)
        if not 0.0 <= self.yes_price <= 1.0:
            raise ValueError("yes_price must be between 0 and 1")
        if self.resolved_at is not None:
            _parse_time(self.resolved_at)
        if self.resolved_yes is not None and self.resolved_at is None:
            raise ValueError("resolved outcomes require resolved_at")

    def to_market(self) -> dict:
        """Return only fields knowable at observation time."""
        return {
            "id": self.market_id,
            "question": self.question,
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps([
                str(self.yes_price), str(1.0 - self.yes_price),
            ]),
            "liquidity": self.liquidity,
            "volume": self.volume,
            "category": self.category,
        }


class HistoricalMarketStore:
    """Versioned JSON storage for timestamped market observations."""

    def __init__(self, path: str | Path = "data/historical_markets.json") -> None:
        self.path = Path(path)
        self.invalid_records = 0

    def load(self) -> list[HistoricalMarketSnapshot]:
        self.invalid_records = 0
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.invalid_records = 1
            raise PersistenceCorruptionError(
                self.path, "historical market file is unreadable or malformed"
            ) from error
        if isinstance(payload, dict):
            if "records" not in payload:
                self.invalid_records = 1
                raise PersistenceCorruptionError(
                    self.path, "historical market state is missing its records collection"
                )
            records = payload["records"]
        else:
            records = payload
        if not isinstance(records, list):
            self.invalid_records = 1
            raise PersistenceCorruptionError(
                self.path, "historical market records must be a list"
            )
        snapshots = []
        for index, record in enumerate(records):
            try:
                snapshots.append(HistoricalMarketSnapshot(**record))
            except (TypeError, ValueError) as error:
                self.invalid_records += 1
                raise PersistenceCorruptionError(
                    self.path, f"historical market record {index} is invalid"
                ) from error
        return snapshots

    def save(self, snapshots: list[HistoricalMarketSnapshot]) -> None:
        if self.path.exists():
            self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "version": 1,
            "records": [asdict(item) for item in snapshots],
        }, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def capture_market(self, market: dict, observed_at: datetime) -> None:
        try:
            prices = json.loads(market.get("outcomePrices", "[]"))
            outcomes = json.loads(market.get("outcomes", "[]"))
            yes_index = next(
                index for index, outcome in enumerate(outcomes)
                if str(outcome).lower() == "yes"
            )
            yes_price = float(prices[yes_index])
            snapshot = HistoricalMarketSnapshot(
                market_id=str(market.get("id") or market.get("conditionId") or ""),
                question=str(market.get("question") or ""),
                observed_at=observed_at.astimezone(timezone.utc).isoformat(),
                yes_price=yes_price,
                resolved_yes=market.get("resolved_yes"),
                resolved_at=market.get("resolved_at"),
                liquidity=self._optional_float(market.get("liquidity")),
                volume=self._optional_float(market.get("volume")),
                category=str(market.get("category") or "OTHER"),
            )
        except (StopIteration, TypeError, ValueError, json.JSONDecodeError):
            return
        snapshots = self.load()
        snapshots.append(snapshot)
        self.save(snapshots)

    @staticmethod
    def _optional_float(value) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class HistoricalIntelligenceRecord:
    title: str
    summary: str
    source: str
    source_url: str
    published_at: str
    available_at: str
    category: str = "OTHER"
    country: str | None = None
    significance: float | None = None
    confidence: float | None = None
    market_sensitivity: float | None = None
    provider: str | None = None
    publisher: str | None = None
    record_id: str | None = None

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("historical event title is required")
        _parse_time(self.published_at)
        _parse_time(self.available_at)

    def to_event(self) -> GeoPoliticalEvent:
        return GeoPoliticalEvent(
            title=self.title, summary=self.summary, category=self.category,
            subcategory="", country=self.country, region=None, continent=None,
            significance=self.significance, confidence=self.confidence,
            market_sensitivity=self.market_sensitivity, source_url=self.source_url,
            published_at=_parse_time(self.published_at),
            available_at=_parse_time(self.available_at), source=self.source,
            provider=self.provider or self.source,
            publisher=self.publisher or "",
        )


class HistoricalIntelligenceStore:
    """Versioned archive of normalized intelligence and ingestion time."""

    def __init__(self, path: str | Path = "data/historical_intelligence.json") -> None:
        self.path = Path(path)
        self.invalid_records = 0

    def load(self) -> list[HistoricalIntelligenceRecord]:
        self.invalid_records = 0
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            self.invalid_records = 1
            raise PersistenceCorruptionError(
                self.path, "historical intelligence file is unreadable or malformed"
            ) from error
        if isinstance(payload, dict):
            if "records" not in payload:
                self.invalid_records = 1
                raise PersistenceCorruptionError(
                    self.path,
                    "historical intelligence state is missing its records collection",
                )
            records = payload["records"]
        else:
            records = payload
        if not isinstance(records, list):
            self.invalid_records = 1
            raise PersistenceCorruptionError(
                self.path, "historical intelligence records must be a list"
            )
        events = []
        for index, record in enumerate(records):
            try:
                events.append(HistoricalIntelligenceRecord(**record))
            except (TypeError, ValueError) as error:
                self.invalid_records += 1
                raise PersistenceCorruptionError(
                    self.path, f"historical intelligence record {index} is invalid"
                ) from error
        return events

    def save(self, records: list[HistoricalIntelligenceRecord]) -> None:
        if self.path.exists():
            self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps({
            "version": 1, "records": [asdict(item) for item in records],
        }, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def capture_events(self, events: list[GeoPoliticalEvent]) -> None:
        available_at = datetime.now(timezone.utc).isoformat()
        records = self.load()
        known = {(item.source, item.source_url, item.published_at) for item in records}
        for event in events:
            if not isinstance(event.published_at, datetime):
                continue
            published_at = event.published_at
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            record = HistoricalIntelligenceRecord(
                title=event.title, summary=event.summary, source=event.source,
                source_url=event.source_url, published_at=published_at.isoformat(),
                available_at=available_at, category=event.category,
                country=event.country, significance=event.significance,
                confidence=event.confidence,
                market_sensitivity=event.market_sensitivity,
            )
            key = (record.source, record.source_url, record.published_at)
            if key not in known:
                records.append(record)
                known.add(key)
        self.save(records)


class HistoricalIntelligenceProvider(IntelligenceProvider):
    """Expose only intelligence that was available by a replay timestamp."""

    def __init__(self, records: list[HistoricalIntelligenceRecord], as_of: datetime) -> None:
        self.records = records
        self.as_of = as_of

    def fetch(self, query=None, limit=100, sort="recent") -> list[GeoPoliticalEvent]:
        available = [
            record for record in self.records
            if _parse_time(record.available_at) <= self.as_of
            and _parse_time(record.published_at) <= self.as_of
        ]
        available.sort(key=lambda item: _parse_time(item.published_at), reverse=True)
        return [deepcopy(item.to_event()) for item in available[:limit]]


class _HistoricalRecorder:
    """In-memory paper recorder used by the unchanged pipeline and risk manager."""

    def __init__(self) -> None:
        self.decisions: list[PaperDecision] = []
        self.observed_at = datetime.now(timezone.utc)

    def load(self) -> list[PaperDecision]:
        return self.decisions

    def record(self, decision: StrategyDecision) -> PaperDecision:
        paper = PaperDecision.from_strategy_decision(decision, "historical-replay")
        paper.timestamp = self.observed_at.isoformat()
        self.decisions.append(paper)
        return paper


@dataclass(frozen=True)
class HistoricalBacktestReport:
    markets_analyzed: int
    opportunities_found: int
    decisions: tuple[PaperDecision, ...]
    analytics: AnalyticsReport
    roi: float
    maximum_drawdown: float
    performance_by_market_category: dict[str, AnalyticsSummary]
    invalid_records: int = 0

    @property
    def simulated_trades(self) -> int:
        return self.analytics.summary.executed_trades


PipelineFactory = Callable[[datetime, _HistoricalRecorder], "IntelligencePipeline"]


class HistoricalReplayEngine:
    """Replay timestamped snapshots through the existing production pipeline."""

    def __init__(
        self,
        intelligence: list[HistoricalIntelligenceRecord],
        pipeline_factory: PipelineFactory | None = None,
    ) -> None:
        self.intelligence = intelligence
        self.pipeline_factory = pipeline_factory or self._pipeline

    def _pipeline(
        self,
        as_of: datetime,
        recorder: _HistoricalRecorder,
    ) -> "IntelligencePipeline":
        from src.intelligence.pipeline import IntelligencePipeline

        provider = HistoricalIntelligenceProvider(self.intelligence, as_of)
        client = IntelligenceClient([provider], evidence_time=as_of)
        return IntelligencePipeline(client, paper_trader=recorder, as_of=as_of)

    def replay(
        self,
        snapshots: list[HistoricalMarketSnapshot],
        invalid_records: int = 0,
    ) -> HistoricalBacktestReport:
        valid = []
        for snapshot in snapshots:
            try:
                observed = _parse_time(snapshot.observed_at)
                resolved = _parse_time(snapshot.resolved_at) if snapshot.resolved_at else None
            except (AttributeError, TypeError, ValueError):
                invalid_records += 1
                continue
            if resolved is not None and resolved <= observed:
                invalid_records += 1
                continue
            valid.append((observed, snapshot))
        valid.sort(key=lambda item: item[0])

        recorder = _HistoricalRecorder()
        pending: list[tuple[datetime, bool, PaperDecision]] = []
        opportunities = 0
        for observed, snapshot in valid:
            self._settle_due(pending, observed)
            recorder.observed_at = observed
            before = len(recorder.decisions)
            decisions = self.pipeline_factory(observed, recorder).run([snapshot.to_market()])
            opportunities += len(decisions)
            new_records = recorder.decisions[before:]
            if snapshot.resolved_at is not None and snapshot.resolved_yes is not None:
                resolved_at = _parse_time(snapshot.resolved_at)
                pending.extend(
                    (resolved_at, snapshot.resolved_yes, decision)
                    for decision in new_records
                )

        self._settle_due(pending, datetime.max.replace(tzinfo=timezone.utc))
        records = recorder.load()
        analytics = PerformanceAnalytics().analyze(records)
        capital = sum(self._capital_at_risk(item) for item in records if item.result in {"WIN", "LOSS"})
        categories: dict[str, list[PaperDecision]] = {}
        for decision in records:
            categories.setdefault(str(decision.market.get("category") or "OTHER"), []).append(decision)
        return HistoricalBacktestReport(
            markets_analyzed=len(valid), opportunities_found=opportunities,
            decisions=tuple(records), analytics=analytics,
            roi=analytics.summary.profit_loss / capital if capital else 0.0,
            maximum_drawdown=BacktestEngine._maximum_drawdown(records),
            performance_by_market_category={
                key: PerformanceAnalytics().analyze(items).summary
                for key, items in categories.items()
            },
            invalid_records=invalid_records,
        )

    def replay_from_store(self, store: HistoricalMarketStore) -> HistoricalBacktestReport:
        snapshots = store.load()
        return self.replay(snapshots, store.invalid_records)

    @staticmethod
    def _settle_due(
        pending: list[tuple[datetime, bool, PaperDecision]],
        as_of: datetime,
    ) -> None:
        due = [item for item in pending if item[0] <= as_of]
        pending[:] = [item for item in pending if item[0] > as_of]
        for resolved_at, resolved_yes, decision in due:
            PaperTradingRecorder.calculate_outcome(
                decision,
                resolved_yes,
                resolved_at=resolved_at.isoformat(),
            )

    @staticmethod
    def _capital_at_risk(decision: PaperDecision) -> float:
        """Return the fraction of portfolio capital staked on a trade."""
        if decision.decision in {
            StrategyAction.BUY_YES.value,
            StrategyAction.BUY_NO.value,
        }:
            return decision.position_size
        return 0.0
