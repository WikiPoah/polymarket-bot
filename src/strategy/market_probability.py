# File-Version: 1.0.0
"""
Market probability extraction.
"""

import json
import math

from src.models import TradingOpportunity


class MarketProbabilityExtractor:
    """
    Extracts the market's implied probability for the expected outcome.
    """

    def extract(self, opportunity: TradingOpportunity) -> float | None:
        """
        Return the YES price, or ``None`` when no valid tradable price exists.
        """

        market = opportunity.market

        try:
            outcomes = json.loads(
                market.get("outcomes", "[]")
            )

            prices = json.loads(
                market.get("outcomePrices", "[]")
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

        if (
            not isinstance(outcomes, list)
            or not isinstance(prices, list)
            or len(outcomes) != len(prices)
        ):
            return None

        yes_prices = [
            price
            for outcome, price in zip(outcomes, prices)
            if isinstance(outcome, str) and outcome.strip().casefold() == "yes"
        ]
        if len(yes_prices) != 1:
            return None

        return self._valid_price(yes_prices[0])

    @staticmethod
    def _valid_price(price) -> float | None:
        try:
            value = float(price)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(value) or not 0.0 < value < 1.0:
            return None

        return value
