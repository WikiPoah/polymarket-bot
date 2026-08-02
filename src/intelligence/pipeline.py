"""
Intelligence pipeline.

Coordinates retrieval, classification, scoring and matching
of geopolitical events against active Polymarket markets.
"""

from src.intelligence.classification import EventType
from src.intelligence.client import IntelligenceClient
from src.intelligence.classifier import EventClassifier
from src.intelligence.market_classifier import MarketClassifier
from src.intelligence.matcher import find_matching_markets
from src.intelligence.outcome_classifier import OutcomeClassifier
from src.intelligence.query_builder import MarketQueryBuilder
from src.intelligence.scorer import score_events
from src.models import GeoPoliticalEvent
from src.strategy.engine import (
    StrategyDecision,
    StrategyEngine,
)
from src.paper_trading.history import PaperTradingRecorder
from src.strategy.portfolio_risk import PortfolioRiskManager


class IntelligencePipeline:
    """
    Runs the complete intelligence pipeline.
    """

    def __init__(
        self,
        client: IntelligenceClient,
        paper_trader: PaperTradingRecorder | None = None,
    ) -> None:

        self._client = client
        self._event_classifier = EventClassifier()
        self._outcome_classifier = OutcomeClassifier()
        self._market_classifier = MarketClassifier()
        self._query_builder = MarketQueryBuilder()
        self._strategy_engine = StrategyEngine()
        self._paper_trader = paper_trader
        self._portfolio_risk = PortfolioRiskManager()

    @property
    def provider_status(self) -> dict[str, str]:
        return self._client.provider_status

    @property
    def provider_errors(self) -> list[str]:
        return self._client.provider_errors

    @property
    def provider_details(self) -> dict[str, dict]:
        return self._client.provider_details

    def reset_provider_status(self) -> None:
        self._client.reset_status()

    def _is_relevant(
        self,
        event: GeoPoliticalEvent,
        market,
    ) -> bool:
        """
        Check whether an event is relevant to a market.
        """

        #
        # Leadership markets require strong evidence.
        #

        if market.event_type == EventType.LEADERSHIP:

            actor_match = any(
                actor in event.actors
                for actor in market.actors
            )

            ccp_match = (
                "Xi Jinping" in market.actors
                and "China" in market.countries
                and "CCP" in event.actors
            )

            if actor_match or ccp_match:
                return True

            if (
                event.event_type == EventType.LEADERSHIP
                and any(
                    country in event.countries
                    for country in market.countries
                )
            ):
                return True

            return False

        #
        # Other markets use actor/country matching.
        #

        if market.actors:

            if any(
                actor in event.actors
                for actor in market.actors
            ):
                return True

        if market.countries:

            if any(
                country in event.countries
                for country in market.countries
            ):
                return True

        return False

    def run(
        self,
        markets: list[dict],
    ) -> list[StrategyDecision]:

        classified_markets = [
            self._market_classifier.classify(market)
            for market in markets
        ]

        decisions: list[StrategyDecision] = []

        for classified_market in classified_markets:

            query = self._query_builder.build(
                classified_market
            )

            print(f"Query: {query}")

            events = self._client.fetch(
                query=query,
                limit=100,
            )

            print(
                f"Events retrieved: {len(events)}"
            )

            classified_events = []

            for event in events:

                event = self._event_classifier.classify(event)
                event = self._outcome_classifier.classify(event)

                print()
                print("FILTER DEBUG:")
                print(event.title)
                print(
                    "Countries:",
                    event.countries,
                )
                print(
                    "Actors:",
                    event.actors,
                )
                print(
                    "Event Type:",
                    event.event_type,
                )
                print(
                    "Outcome:",
                    event.outcome,
                )

                if self._is_relevant(
                    event,
                    classified_market,
                ):
                    classified_events.append(event)

            print(
                f"Relevant events: {len(classified_events)}"
            )

            scored_events = score_events(
                classified_events,
                classified_market,
            )

            print(
                f"Events scored: {len(scored_events)}"
            )

            for scored_event in scored_events[:5]:

                print()
                print("DEBUG EVENT:")
                print(
                    scored_event.event.title
                )
                print(
                    "Countries:",
                    scored_event.event.countries,
                )
                print(
                    "Actors:",
                    scored_event.event.actors,
                )
                print(
                    "Event Type:",
                    scored_event.event.event_type,
                )

            for scored_event in scored_events:

                opportunities = find_matching_markets(
                    scored_event,
                    [classified_market],
                )

                print(
                    f"Matches found: {len(opportunities)}"
                )

                for opportunity in opportunities:

                    decision = self._strategy_engine.evaluate(opportunity)
                    if self._paper_trader is not None:
                        decision = self._portfolio_risk.apply(
                            decision,
                            self._paper_trader.load(),
                        )
                    decisions.append(decision)
                    if self._paper_trader is not None:
                        self._paper_trader.record(decision)

        decisions.sort(
            key=lambda decision: (
                decision.expected_value,
                decision.edge,
            ),
            reverse=True,
        )

        return decisions
