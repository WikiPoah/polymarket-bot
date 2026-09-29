# File-Version: 1.1.0
"""
Strategy engine.

The strategy engine consumes TradingOpportunity objects produced by the
intelligence pipeline and determines whether a market is worth trading.
"""

from datetime import datetime

from dataclasses import dataclass

from src.models import TradingOpportunity
from src.strategy.expected_value import (
    ExpectedValueCalculator,
    StrategyAction,
)
from src.strategy.market_probability import MarketProbabilityExtractor
from src.strategy.position_sizing import PositionSizer
from src.strategy.probability import ProbabilityEstimator
from src.strategy.risk import RiskManager


@dataclass(slots=True)
class StrategyDecision:
    """
    Represents the output of the strategy engine.

    ``position_size`` is the fraction of portfolio capital staked on the
    selected side, not the number of prediction-market shares purchased.
    """

    opportunity: TradingOpportunity

    action: StrategyAction

    estimated_probability: float
    market_probability: float | None

    edge: float
    expected_value: float

    confidence: float

    position_size: float

    reasons: list[str]


class StrategyEngine:
    """
    Consumes trading opportunities and produces trading decisions.
    """

    def __init__(self, as_of: datetime | None = None) -> None:
        self._probability_estimator = ProbabilityEstimator(as_of=as_of)
        self._market_probability = MarketProbabilityExtractor()
        self._ev_calculator = ExpectedValueCalculator()
        self._position_sizer = PositionSizer()
        self._risk_manager = RiskManager()

    def evaluate(
        self,
        opportunity: TradingOpportunity,
    ) -> StrategyDecision:
        """
        Evaluate a trading opportunity.
        """

        estimated_probability = (
            self._probability_estimator.estimate(
                opportunity
            )
        )

        market_probability = (
            self._market_probability.extract(
                opportunity
            )
        )

        intelligence_confidence = max(
            0.0,
            min(
                opportunity.event.event.evidence_confidence,
                1.0,
            ),
        )

        decision_confidence = round(
            opportunity.confidence
            * intelligence_confidence,
            2,
        )

        if market_probability is None:
            return StrategyDecision(
                opportunity=opportunity,
                action=StrategyAction.IGNORE,
                estimated_probability=estimated_probability,
                market_probability=None,
                edge=0.0,
                expected_value=0.0,
                confidence=decision_confidence,
                position_size=0.0,
                reasons=[
                    "Ignored: invalid market probability; no valid tradable "
                    "YES price was available."
                ],
            )

        edge, expected_value, proposed_action = (
            self._ev_calculator.calculate(
                estimated_probability,
                market_probability,
            )
        )

        action = self._risk_manager.apply(
            action=proposed_action,
            edge=edge,
            expected_value=expected_value,
            confidence=decision_confidence,
        )

        reasons = self._explain(
            proposed_action=proposed_action,
            action=action,
            estimated_probability=estimated_probability,
            market_probability=market_probability,
            edge=edge,
            expected_value=expected_value,
            confidence=decision_confidence,
        )

        position_size = 0.0

        if action != StrategyAction.IGNORE:
            position_size = (
                self._position_sizer.calculate(
                    edge,
                    decision_confidence,
                )
            )

        return StrategyDecision(
            opportunity=opportunity,
            action=action,
            estimated_probability=estimated_probability,
            market_probability=market_probability,
            edge=edge,
            expected_value=expected_value,
            confidence=decision_confidence,
            position_size=position_size,
            reasons=reasons,
        )

    def _explain(
        self,
        proposed_action: StrategyAction,
        action: StrategyAction,
        estimated_probability: float,
        market_probability: float,
        edge: float,
        expected_value: float,
        confidence: float,
    ) -> list[str]:
        comparison = (
            f"Bot estimate {estimated_probability:.1%} versus market "
            f"{market_probability:.1%}; edge {edge:+.1%} and confidence "
            f"{confidence:.1%}."
        )
        if proposed_action == StrategyAction.IGNORE:
            return [comparison, "Ignored: the bot found no pricing edge."]
        if action == StrategyAction.IGNORE:
            if confidence < self._risk_manager.MIN_CONFIDENCE:
                reason = (
                    f"Ignored: confidence {confidence:.1%} is below the "
                    f"required {self._risk_manager.MIN_CONFIDENCE:.1%}."
                )
            elif abs(edge) < self._risk_manager.MIN_EDGE:
                reason = (
                    f"Ignored: absolute edge {abs(edge):.1%} is below the "
                    f"required {self._risk_manager.MIN_EDGE:.1%}."
                )
            elif expected_value < self._risk_manager.MIN_EXPECTED_VALUE:
                reason = (
                    f"Ignored: expected value {expected_value:.1%} is below "
                    f"the required {self._risk_manager.MIN_EXPECTED_VALUE:.1%}."
                )
            else:
                reason = "Ignored: the opportunity failed a strategy risk rule."
            return [comparison, reason]
        return [
            comparison,
            f"Accepted: {action.value} passed the strategy thresholds.",
        ]
