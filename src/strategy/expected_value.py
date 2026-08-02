"""
Expected value calculation.
"""

from enum import Enum


class StrategyAction(Enum):
    """
    Possible actions returned by the strategy engine.
    """

    BUY_YES = "BUY YES"
    BUY_NO = "BUY NO"
    IGNORE = "IGNORE"


class ExpectedValueCalculator:
    """
    Calculates the expected value of a potential trade.
    """

    def calculate(
        self,
        estimated_probability: float,
        market_probability: float,
    ) -> tuple[float, float, StrategyAction]:
        """
        Returns:
            edge,
            expected_value,
            recommended_action
        """

        edge = estimated_probability - market_probability

        if edge > 0:
            action = StrategyAction.BUY_YES
        elif edge < 0:
            action = StrategyAction.BUY_NO
        else:
            action = StrategyAction.IGNORE

        expected_value = abs(edge)

        return edge, expected_value, action