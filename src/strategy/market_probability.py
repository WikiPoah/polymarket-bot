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

        try:
            outcomes = json.loads(
                market.get("outcomes", "[]")
            )

            prices = json.loads(
                market.get("outcomePrices", "[]")
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0.5

        if len(outcomes) != len(prices):
            return 0.5

        expected_outcome = opportunity.expected_outcome

        if expected_outcome.name != "OTHER":
            expected = (
                expected_outcome.name
                .replace("_", " ")
                .title()
            )

            for outcome, price in zip(outcomes, prices):
                if outcome.lower() == expected.lower():
                    return self._valid_price(price)

            # Binary Polymarket markets represent the classified
            # expected outcome as YES when no explicit label exists.
            for outcome, price in zip(outcomes, prices):
                if outcome.lower() == "yes":
                    return self._valid_price(price)

        event_outcome = opportunity.event.event.outcome
        expected = (
            event_outcome.name
            .replace("_", " ")
            .title()
        )

        for outcome, price in zip(outcomes, prices):
            if outcome.lower() == expected.lower():
                return self._valid_price(price)

        return 0.5

    @staticmethod
    def _valid_price(price) -> float:
        try:
            value = float(price)
        except (TypeError, ValueError):
            return 0.5

        if not 0.0 <= value <= 1.0:
            return 0.5

        return value
