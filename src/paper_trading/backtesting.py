"""Historical replay and scenario evaluation for paper-trading records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from src.paper_trading.analytics import AnalyticsReport, AnalyticsSummary, PerformanceAnalytics
from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision
from src.strategy.expected_value import StrategyAction


@dataclass(frozen=True)
class BacktestConfig:
    """Filters used to evaluate a recorded-decision strategy scenario."""

    minimum_confidence: float = 0.0
    minimum_edge: float = 0.0
    event_types: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be between 0 and 1")
        if self.minimum_edge < 0.0:
            raise ValueError("minimum_edge cannot be negative")


@dataclass(frozen=True)
class BacktestReport:
    """Results from one chronological historical replay."""

    decisions: tuple[PaperDecision, ...]
    analytics: AnalyticsReport
    maximum_drawdown: float
    invalid_records: int = 0

    @property
    def summary(self) -> AnalyticsSummary:
        return self.analytics.summary

    @property
    def performance_by_event_type(self) -> dict[str, AnalyticsSummary]:
        return self.analytics.by_event_type


class BacktestEngine:
    """Replay persisted decisions without invoking execution or changing strategy logic."""

    _TRADE_ACTIONS = {
        StrategyAction.BUY_YES.value,
        StrategyAction.BUY_NO.value,
    }

    def __init__(self, analytics: PerformanceAnalytics | None = None) -> None:
        self.analytics = analytics or PerformanceAnalytics()

    def load(self, recorder: PaperTradingRecorder) -> list[PaperDecision]:
        """Load records using the existing paper-trading persistence boundary."""
        return recorder.load()

    def run_from_recorder(
        self,
        recorder: PaperTradingRecorder,
        config: BacktestConfig | None = None,
    ) -> BacktestReport:
        return self.run(self.load(recorder), config)

    def run(
        self,
        decisions: Iterable[PaperDecision],
        config: BacktestConfig | None = None,
    ) -> BacktestReport:
        config = config or BacktestConfig()
        chronological: list[tuple[datetime, PaperDecision]] = []
        invalid_records = 0

        for original in decisions:
            try:
                timestamp = datetime.fromisoformat(original.timestamp)
                replayed = PaperDecision.from_dict(original.to_dict())
            except (AttributeError, TypeError, ValueError):
                invalid_records += 1
                continue
            if not self._eligible(replayed, config):
                continue
            if replayed.resolved_yes is not None:
                PaperTradingRecorder.calculate_outcome(replayed, replayed.resolved_yes)
            chronological.append((timestamp, replayed))

        replayed_decisions = [item[1] for item in sorted(chronological, key=lambda item: item[0])]
        analytics = self.analytics.analyze(replayed_decisions)
        return BacktestReport(
            decisions=tuple(replayed_decisions),
            analytics=analytics,
            maximum_drawdown=self._maximum_drawdown(replayed_decisions),
            invalid_records=invalid_records,
        )

    def compare(
        self,
        decisions: Iterable[PaperDecision],
        scenarios: Mapping[str, BacktestConfig],
    ) -> dict[str, BacktestReport]:
        """Evaluate confidence, edge, or category configurations side by side."""
        history = list(decisions)
        return {name: self.run(history, config) for name, config in scenarios.items()}

    def _eligible(self, decision: PaperDecision, config: BacktestConfig) -> bool:
        if decision.decision not in self._TRADE_ACTIONS:
            return False
        if decision.confidence < config.minimum_confidence:
            return False
        if abs(decision.edge) < config.minimum_edge:
            return False
        return config.event_types is None or decision.event_type in config.event_types

    @staticmethod
    def _maximum_drawdown(decisions: list[PaperDecision]) -> float:
        balance = 0.0
        peak = 0.0
        maximum = 0.0
        settled = [item for item in decisions if item.result in {"WIN", "LOSS"}]
        settled.sort(key=lambda item: item.resolved_at or item.timestamp)
        for decision in settled:
            balance += decision.profit_loss
            peak = max(peak, balance)
            maximum = max(maximum, peak - balance)
        return maximum
