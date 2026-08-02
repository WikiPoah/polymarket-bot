"""
Intelligence pipeline.

Coordinates retrieval, classification, scoring and matching
of geopolitical events against active Polymarket markets.
"""

from src.intelligence.classifier import EventClassifier
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.matcher import find_matching_markets
from src.intelligence.outcome_classifier import OutcomeClassifier
from src.intelligence.provider import IntelligenceProvider
from src.intelligence.scorer import score_events
from src.models import TradingOpportunity


class IntelligencePipeline:
    """
    Runs the complete intelligence pipeline.
    """

    def __init__(
        self,
        provider: IntelligenceProvider,
    ) -> None:

        self._provider = provider
        self._event_classifier = EventClassifier()
        self._outcome_classifier = OutcomeClassifier()
        self._market_classifier = MarketClassifier()

    def run(
        self,
        markets: list[dict],
    ) -> list[TradingOpportunity]:

        events = self._provider.fetch(limit=100)

        classified_events = []

        for event in events:

            event = self._event_classifier.classify(event)
            event = self._outcome_classifier.classify(event)

            classified_events.append(event)

        classified_markets = [
            self._market_classifier.classify(market)
            for market in markets
        ]

        scored_events = score_events(classified_events)

        opportunities: list[TradingOpportunity] = []

        for scored_event in scored_events:

            opportunities.extend(
                find_matching_markets(
                    scored_event,
                    classified_markets,
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