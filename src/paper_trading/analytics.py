"""Performance, strategy-breakdown, and probability-calibration analytics."""

from dataclasses import dataclass

from src.paper_trading.models import PaperDecision
from src.strategy.expected_value import StrategyAction


@dataclass(frozen=True)
class AnalyticsSummary:
    total_decisions: int
    executed_trades: int
    wins: int
    losses: int
    win_rate: float
    profit_loss: float
    average_edge: float
    average_confidence: float


@dataclass(frozen=True)
class CalibrationBucket:
    lower_bound: float
    upper_bound: float
    count: int
    average_predicted: float
    actual_rate: float


@dataclass(frozen=True)
class AnalyticsReport:
    summary: AnalyticsSummary
    by_event_type: dict[str, AnalyticsSummary]
    by_confidence: dict[str, AnalyticsSummary]
    by_evidence_strength: dict[str, AnalyticsSummary]
    calibration: list[CalibrationBucket]
    brier_score: float | None


class PerformanceAnalytics:
    """Compute analytics from records, independent of storage and execution."""

    _BINS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.01)

    def analyze(self, decisions: list[PaperDecision]) -> AnalyticsReport:
        summary = self._summary(decisions)
        by_event_type = self._grouped(decisions, lambda item: item.event_type)
        by_confidence = self._grouped(decisions, self._confidence_band)
        by_evidence = self._grouped(decisions, self._evidence_band)
        calibration, brier_score = self._calibration(decisions)
        return AnalyticsReport(
            summary=summary,
            by_event_type=by_event_type,
            by_confidence=by_confidence,
            by_evidence_strength=by_evidence,
            calibration=calibration,
            brier_score=brier_score,
        )

    def _summary(self, decisions: list[PaperDecision]) -> AnalyticsSummary:
        trades = [item for item in decisions if self._is_trade(item)]
        settled = [item for item in trades if item.result in {"WIN", "LOSS"}]
        wins = sum(item.result == "WIN" for item in settled)
        losses = sum(item.result == "LOSS" for item in settled)
        return AnalyticsSummary(
            total_decisions=len(decisions),
            executed_trades=len(trades),
            wins=wins,
            losses=losses,
            win_rate=wins / len(settled) if settled else 0.0,
            profit_loss=sum(item.profit_loss for item in settled),
            average_edge=self._average(item.edge for item in decisions),
            average_confidence=self._average(item.confidence for item in decisions),
        )

    def _grouped(self, decisions, key_function):
        groups: dict[str, list[PaperDecision]] = {}
        for decision in decisions:
            groups.setdefault(key_function(decision), []).append(decision)
        return {key: self._summary(items) for key, items in groups.items()}

    @staticmethod
    def _average(values) -> float:
        values = list(values)
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _is_trade(decision: PaperDecision) -> bool:
        return decision.decision in {
            StrategyAction.BUY_YES.value,
            StrategyAction.BUY_NO.value,
        }

    @staticmethod
    def _confidence_band(decision: PaperDecision) -> str:
        if decision.confidence < 0.6:
            return "LOW"
        if decision.confidence < 0.8:
            return "MEDIUM"
        return "HIGH"

    @staticmethod
    def _evidence_band(decision: PaperDecision) -> str:
        if decision.evidence_count <= 1:
            return "SINGLE_SOURCE"
        if decision.evidence_count <= 2:
            return "MULTI_SOURCE"
        return "STRONG_MULTI_SOURCE"

    def _calibration(self, decisions):
        observations = []
        for decision in decisions:
            if not self._is_trade(decision) or decision.result not in {"WIN", "LOSS"}:
                continue
            predicted = decision.estimated_probability
            if decision.decision == StrategyAction.BUY_NO.value:
                predicted = 1.0 - predicted
            actual = 1.0 if decision.result == "WIN" else 0.0
            observations.append((max(0.0, min(predicted, 1.0)), actual))

        if not observations:
            return [], None

        buckets = []
        for lower, upper in zip(self._BINS, self._BINS[1:]):
            values = [item for item in observations if lower <= item[0] < upper]
            if not values:
                continue
            buckets.append(CalibrationBucket(
                lower_bound=lower,
                upper_bound=min(upper, 1.0),
                count=len(values),
                average_predicted=self._average(item[0] for item in values),
                actual_rate=self._average(item[1] for item in values),
            ))
        brier = self._average((predicted - actual) ** 2 for predicted, actual in observations)
        return buckets, brier


def format_report(report: AnalyticsReport) -> str:
    """Render a compact human-readable analytics report."""

    summary = report.summary
    lines = [
        "Paper Trading Performance",
        f"Decisions: {summary.total_decisions}",
        f"Executed trades: {summary.executed_trades}",
        f"Wins/Losses: {summary.wins}/{summary.losses}",
        f"Win rate: {summary.win_rate:.1%}",
        f"Profit/Loss: {summary.profit_loss:+.4f}",
        f"Average edge: {summary.average_edge:+.1%}",
        f"Average confidence: {summary.average_confidence:.1%}",
    ]
    if report.brier_score is not None:
        lines.append(f"Brier score: {report.brier_score:.4f}")
    return "\n".join(lines)
