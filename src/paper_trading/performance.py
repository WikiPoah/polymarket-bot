"""Performance metrics for paper-trading history."""

from dataclasses import dataclass

from src.paper_trading.models import PaperDecision


@dataclass(frozen=True)
class PerformanceMetrics:
    number_decisions: int
    winning_decisions: int
    losing_decisions: int
    win_rate: float
    profit_loss: float


class PerformanceTracker:
    """Calculate metrics without coupling to persistence or execution."""

    def calculate(self, decisions: list[PaperDecision]) -> PerformanceMetrics:
        settled = [decision for decision in decisions if decision.result in {"WIN", "LOSS"}]
        wins = sum(decision.result == "WIN" for decision in settled)
        losses = sum(decision.result == "LOSS" for decision in settled)
        total = wins + losses
        return PerformanceMetrics(
            number_decisions=len(decisions),
            winning_decisions=wins,
            losing_decisions=losses,
            win_rate=wins / total if total else 0.0,
            profit_loss=sum(decision.profit_loss for decision in settled),
        )
