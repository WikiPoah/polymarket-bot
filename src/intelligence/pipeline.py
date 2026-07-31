"""
Intelligence pipeline.

Coordinates retrieval, scoring and matching of geopolitical
events against active Polymarket markets.
"""

from src.intelligence.matcher import (
    find_matching_markets,
)
from src.intelligence.provider import (
    IntelligenceProvider,
)
from src.intelligence.scorer import (
    score_events,
)
from src.models import (
    TradingOpportunity,
)


class IntelligencePipeline:
    """
    Runs the complete intelligence pipeline.
    """

    def __init__(
        self,
        provider: IntelligenceProvider,
    ) -> None:
        """
        Initialise the intelligence pipeline.

        Args:
            provider:
                Intelligence provider.
        """

        self._provider = provider

    def run(
        self,
        markets: list[dict],
    ) -> list[TradingOpportunity]:
        """
        Execute the complete intelligence pipeline.

        Args:
            markets:
                Active Polymarket markets.

        Returns:
            Trading opportunities sorted by relevance.
        """

        events = self._provider.fetch(limit=100)

        scored_events = score_events(events)

        opportunities: list[TradingOpportunity] = []

        for scored_event in scored_events:

            opportunities.extend(
                find_matching_markets(
                    scored_event,
                    markets,
                )
            )

        opportunities.sort(
            key=lambda opportunity: (
                opportunity.event.score,
                opportunity.match_score,
            ),
            reverse=True,
        )

        return opportunities