"""
Market probability extraction.
"""

import json

from src.models import TradingOpportunity


class MarketProbabilityExtractor:
    """
    Extracts the market's implied probability for the expected outcome.
    """

    def extract(self, opportunity: TradingOpportunity) -> float:
        """
        Returns the market probability between 0.0 and 1.0.
        """

        market = opportunity.market

        outcomes = json.loads(
            market.get("outcomes", "[]")
        )

        prices = json.loads(
            market.get("outcomePrices", "[]")
        )

        if len(outcomes) != len(prices):
            return 0.5

        expected = (
            opportunity.event.event.outcome.name
            .replace("_", " ")
            .title()
        )

        for outcome, price in zip(outcomes, prices):

            if outcome.lower() == expected.lower():
                return float(price)

        return 0.5