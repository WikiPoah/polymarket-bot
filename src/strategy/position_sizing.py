# File-Version: 1.0.0
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
        Return the fraction of portfolio capital staked on the selected side.

        ``edge`` is expressed from the YES side, so BUY NO opportunities have
        a negative edge. Position size uses the opportunity magnitude for both
        sides while an exact zero edge remains unsized.
        """

        if edge == 0:
            return 0.0

        position_size = abs(edge) * confidence

        return min(position_size, 0.10)
