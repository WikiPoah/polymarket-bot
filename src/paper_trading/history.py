"""JSON decision history for paper trading."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.paper_trading.models import PaperDecision
from src.strategy.engine import StrategyDecision
from src.strategy.expected_value import StrategyAction


class PaperTradingRecorder:
    """Persist decisions and optional binary-market settlements."""

    def __init__(self, path: str | Path = "data/paper_trading_history.json") -> None:
        self.path = Path(path)
        self.run_id = ""
        self.duplicate_window = timedelta(0)

    def begin_run(self, run_id: str, duplicate_window: timedelta) -> None:
        self.run_id = run_id
        self.duplicate_window = duplicate_window

    def load(self) -> list[PaperDecision]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, dict):
            payload = payload.get("records", [])
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
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": 2,
                    "records": [decision.to_dict() for decision in decisions],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def record(self, decision: StrategyDecision) -> PaperDecision | None:
        paper_decision = PaperDecision.from_strategy_decision(decision, self.run_id)
        decisions = self.load()
        if self._is_duplicate(paper_decision, decisions):
            return None
        decisions.append(paper_decision)
        self.save(decisions)
        return paper_decision

    def _is_duplicate(
        self,
        candidate: PaperDecision,
        decisions: list[PaperDecision],
    ) -> bool:
        if self.duplicate_window <= timedelta(0):
            return False
        try:
            candidate_time = datetime.fromisoformat(candidate.timestamp)
        except ValueError:
            return False
        for existing in reversed(decisions):
            if existing.opportunity_id != candidate.opportunity_id:
                continue
            try:
                existing_time = datetime.fromisoformat(existing.timestamp)
            except ValueError:
                continue
            if candidate_time - existing_time <= self.duplicate_window:
                return True
        return False

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
