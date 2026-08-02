"""
Risk management.
"""

from src.strategy.expected_value import StrategyAction


class RiskManager:
    """
    Applies basic risk management rules to trading decisions.
    """

    MIN_EDGE = 0.05
    MIN_CONFIDENCE = 0.60
    MIN_EXPECTED_VALUE = 0.05

    def apply(
        self,
        action: StrategyAction,
        edge: float,
        expected_value: float,
        confidence: float,
    ) -> StrategyAction:
        """
        Validate whether a trade should be taken.
        """

        if action == StrategyAction.IGNORE:
            return action

        if abs(edge) < self.MIN_EDGE:
            return StrategyAction.IGNORE

        if expected_value < self.MIN_EXPECTED_VALUE:
            return StrategyAction.IGNORE

        if confidence < self.MIN_CONFIDENCE:
            return StrategyAction.IGNORE

        return action