"""Portfolio-level safeguards for paper-trading decisions."""

from dataclasses import dataclass, replace
import math

from src.strategy.engine import StrategyDecision
from src.strategy.expected_value import StrategyAction


@dataclass(frozen=True)
class RiskConfig:
    """Configurable limits expressed as fractions of portfolio capital."""

    max_position_size: float = 0.10
    max_portfolio_exposure: float = 0.50
    min_confidence: float = 0.60
    min_edge: float = 0.05
    min_risk_reward: float = 1.0
    starting_capital: float = 1.0


@dataclass(frozen=True)
class PortfolioState:
    """Current simulated allocation derived from paper history."""

    open_positions: int
    exposure: float
    total_capital: float
    available_capital: float

    @classmethod
    def from_decisions(cls, decisions, total_capital: float = 1.0) -> "PortfolioState":
        open_positions = [
            decision for decision in decisions
            if decision.decision in {"BUY YES", "BUY NO"}
            and decision.result is None
        ]
        exposure = sum(decision.position_size for decision in open_positions)
        return cls(
            open_positions=len(open_positions),
            exposure=exposure,
            total_capital=total_capital,
            available_capital=max(total_capital - exposure, 0.0),
        )


@dataclass(frozen=True)
class RiskCheck:
    accepted: bool
    reason: str
    state: PortfolioState


class PortfolioRiskManager:
    """Validate strategy output before it enters paper-trading history."""

    def __init__(self, config: RiskConfig | None = None) -> None:
        self.config = config or RiskConfig()

    def check(self, decision: StrategyDecision, decisions=()) -> RiskCheck:
        state = PortfolioState.from_decisions(
            decisions,
            total_capital=self.config.starting_capital,
        )
        if decision.action == StrategyAction.IGNORE:
            return RiskCheck(True, "Strategy ignored the opportunity.", state)

        values = (
            decision.market_probability,
            decision.estimated_probability,
            decision.edge,
            decision.expected_value,
            decision.confidence,
            decision.position_size,
        )
        if not all(math.isfinite(value) for value in values):
            return RiskCheck(False, "Invalid non-finite opportunity values.", state)
        if not 0.0 <= decision.market_probability <= 1.0:
            return RiskCheck(False, "Invalid market probability.", state)
        if not 0.0 <= decision.estimated_probability <= 1.0:
            return RiskCheck(False, "Invalid estimated probability.", state)
        if decision.confidence < self.config.min_confidence:
            return RiskCheck(False, "Confidence is below the portfolio threshold.", state)
        if abs(decision.edge) < self.config.min_edge:
            return RiskCheck(False, "Edge is below the portfolio threshold.", state)
        if decision.position_size <= 0.0:
            return RiskCheck(False, "Position size must be positive.", state)
        if decision.position_size > self.config.max_position_size:
            return RiskCheck(False, "Position size exceeds the configured maximum.", state)
        if state.exposure + decision.position_size > self.config.max_portfolio_exposure:
            return RiskCheck(False, "Portfolio exposure limit would be exceeded.", state)
        if decision.position_size > state.available_capital:
            return RiskCheck(False, "Insufficient available capital.", state)
        risk_reward = decision.expected_value / decision.position_size
        if risk_reward < self.config.min_risk_reward:
            return RiskCheck(False, "Risk/reward ratio is below the configured minimum.", state)
        return RiskCheck(True, "Opportunity passed portfolio risk checks.", state)

    def apply(self, decision: StrategyDecision, decisions=()) -> StrategyDecision:
        """Return the decision, or a recorded IGNORE decision on rejection."""

        check = self.check(decision, decisions)
        if check.accepted:
            if decision.action == StrategyAction.IGNORE:
                return replace(decision, reasons=[*decision.reasons, check.reason])
            return decision
        return replace(
            decision,
            action=StrategyAction.IGNORE,
            position_size=0.0,
            reasons=[*decision.reasons, f"Risk rejected: {check.reason}"],
        )
