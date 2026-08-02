"""
Position sizing.
"""


class PositionSizer:
    """
    Determines how much capital to allocate to a trade.
    """

    def calculate(
        self,
        edge: float,
        confidence: float,
    ) -> float:
        """
        Returns the recommended position size as a fraction
        of the portfolio.
        """

        if edge <= 0:
            return 0.0

        position_size = edge * confidence

        return min(position_size, 0.10)