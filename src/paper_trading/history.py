"""JSON decision history for paper trading."""

import json
from pathlib import Path

from src.paper_trading.models import PaperDecision
from src.strategy.engine import StrategyDecision
from src.strategy.expected_value import StrategyAction


class PaperTradingRecorder:
    """Persist decisions and optional binary-market settlements."""

    def __init__(self, path: str | Path = "data/paper_trading_history.json") -> None:
        self.path = Path(path)

    def load(self) -> list[PaperDecision]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        decisions = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                decisions.append(PaperDecision.from_dict(item))
            except (TypeError, ValueError):
                # A damaged record must not make the remaining history unreadable.
                continue
        return decisions

    def save(self, decisions: list[PaperDecision]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([decision.to_dict() for decision in decisions], indent=2),
            encoding="utf-8",
        )

    def record(self, decision: StrategyDecision) -> PaperDecision:
        paper_decision = PaperDecision.from_strategy_decision(decision)
        decisions = self.load()
        decisions.append(paper_decision)
        self.save(decisions)
        return paper_decision

    def settle(self, decision_id: str, resolved_yes: bool) -> PaperDecision:
        decisions = self.load()
        for decision in decisions:
            if decision.id != decision_id:
                continue
            self.calculate_outcome(decision, resolved_yes)
            self.save(decisions)
            return decision
        raise KeyError(f"Unknown paper decision: {decision_id}")

    @staticmethod
    def calculate_outcome(decision: PaperDecision, resolved_yes: bool) -> PaperDecision:
        """Apply binary-market settlement math to a paper decision in memory."""
        decision.resolved_yes = resolved_yes
        if decision.decision == StrategyAction.BUY_YES.value:
            won = resolved_yes
            decision.profit_loss = (
                decision.position_size * (1 - decision.market_probability)
                if won
                else -decision.position_size * decision.market_probability
            )
        elif decision.decision == StrategyAction.BUY_NO.value:
            won = not resolved_yes
            decision.profit_loss = (
                decision.position_size * decision.market_probability
                if won
                else -decision.position_size * (1 - decision.market_probability)
            )
        else:
            decision.profit_loss = 0.0
            decision.result = "IGNORED"
            return decision
        decision.result = "WIN" if won else "LOSS"
        return decision
