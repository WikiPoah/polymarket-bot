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
    """

    opportunity: TradingOpportunity

    action: StrategyAction

    estimated_probability: float
    market_probability: float

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

        edge, expected_value, action = (
            self._ev_calculator.calculate(
                estimated_probability,
                market_probability,
            )
        )

        action = self._risk_manager.apply(
            action=action,
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
            reasons=[
                "Probability estimated from intelligence.",
                "Market probability extracted from Polymarket.",
                "Expected value calculated.",
                "Risk rules applied.",
                "Position size determined.",
            ],
        )
