"""
Strategy engine.

The strategy engine consumes TradingOpportunity objects produced by the
intelligence pipeline and determines whether a market is worth trading.
"""

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

    def __init__(self) -> None:
        self._probability_estimator = ProbabilityEstimator()
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
            confidence=opportunity.confidence,
        )

        position_size = 0.0

        if action != StrategyAction.IGNORE:
            position_size = (
                self._position_sizer.calculate(
                    edge,
                    opportunity.confidence,
                )
            )

        return StrategyDecision(
            opportunity=opportunity,
            action=action,
            estimated_probability=estimated_probability,
            market_probability=market_probability,
            edge=edge,
            expected_value=expected_value,
            confidence=opportunity.confidence,
            position_size=position_size,
            reasons=[
                "Probability estimated from intelligence.",
                "Market probability extracted from Polymarket.",
                "Expected value calculated.",
                "Risk rules applied.",
                "Position size determined.",
            ],
        )