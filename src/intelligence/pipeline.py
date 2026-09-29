# File-Version: 1.2.0
"""
Intelligence pipeline.

Coordinates retrieval, classification, scoring and matching
of geopolitical events against active Polymarket markets.
"""

from datetime import datetime
from copy import deepcopy
import logging

from src.intelligence.classification import EventType
from src.intelligence.outcomes import Outcome
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


logger = logging.getLogger(__name__)


class IntelligencePipeline:
    """
    Runs the complete intelligence pipeline.
    """

    def __init__(
        self,
        client: IntelligenceClient,
        paper_trader: PaperTradingRecorder | None = None,
        as_of: datetime | None = None,
    ) -> None:

        self._client = client
        self._event_classifier = EventClassifier()
        self._outcome_classifier = OutcomeClassifier()
        self._market_classifier = MarketClassifier()
        self._query_builder = MarketQueryBuilder()
        self._strategy_engine = StrategyEngine(as_of=as_of)
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

            leadership_evidence = (
                event.event_type == EventType.LEADERSHIP
                or event.outcome == Outcome.LEADER_REMOVED
            )

            if leadership_evidence and (actor_match or ccp_match):
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

        if (
            market.event_type != EventType.OTHER
            and event.event_type != market.event_type
        ):
            return False

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

        logger.info("Evaluating %d classified markets", len(classified_markets))

        for classified_market in classified_markets:

            if not classified_market.supported_proposition:
                logger.info(
                    "Skipping unsupported market question=%r reason=%s",
                    classified_market.market.get("question", ""),
                    classified_market.unsupported_reason,
                )
                continue

            query = self._query_builder.build(
                classified_market
            )

            logger.debug("Intelligence query: %s", query)

            events = self._client.fetch(
                query=query,
                limit=100,
            )

            logger.debug("Retrieved %d events", len(events))

            classified_events = self.classify_events(events)

            decisions.extend(self._evaluate_classified_events(
                classified_market, classified_events,
            ))

        return self._finish(decisions)

    def classify_events(
        self,
        events: list[GeoPoliticalEvent],
    ) -> tuple[GeoPoliticalEvent, ...]:
        """Classify market-independent event features once for safe replay reuse."""
        classified_events = []
        for raw_event in events:
            event = self._event_classifier.classify(deepcopy(raw_event))
            event = self._outcome_classifier.classify(event)

            logger.debug(
                "Classified event title=%r countries=%s actors=%s "
                "event_type=%s outcome=%s",
                event.title,
                event.countries,
                event.actors,
                event.event_type.name,
                event.outcome.name,
            )
            classified_events.append(event)
        return tuple(classified_events)

    def run_classified_events(
        self,
        markets: list[dict],
        classified_events: tuple[GeoPoliticalEvent, ...],
    ) -> list[StrategyDecision]:
        """Evaluate a shared immutable event view without repeating classification."""
        decisions: list[StrategyDecision] = []
        for market in markets:
            classified_market = self._market_classifier.classify(market)
            if not classified_market.supported_proposition:
                logger.info(
                    "Skipping unsupported market question=%r reason=%s",
                    classified_market.market.get("question", ""),
                    classified_market.unsupported_reason,
                )
                continue
            decisions.extend(self._evaluate_classified_events(
                classified_market,
                [deepcopy(event) for event in classified_events],
            ))
        return self._finish(decisions)

    def _evaluate_classified_events(
        self,
        classified_market,
        events: list[GeoPoliticalEvent] | tuple[GeoPoliticalEvent, ...],
    ) -> list[StrategyDecision]:
        if not classified_market.supported_proposition:
            return []

        classified_events = []
        decisions: list[StrategyDecision] = []
        for event in events:

            if self._is_relevant(event, classified_market):
                classified_events.append(event)

        logger.debug("Retained %d relevant events", len(classified_events))

        scored_events = score_events(classified_events, classified_market)

        logger.debug("Scored %d events", len(scored_events))

        for scored_event in scored_events[:5]:

            logger.debug(
                "Top event score=%d title=%r countries=%s actors=%s "
                "event_type=%s",
                scored_event.score,
                scored_event.event.title,
                scored_event.event.countries,
                scored_event.event.actors,
                scored_event.event.event_type.name,
            )

        for scored_event in scored_events:

            opportunities = find_matching_markets(scored_event, [classified_market])

            logger.debug("Found %d market matches", len(opportunities))

            for opportunity in opportunities:

                decision = self._strategy_engine.evaluate(opportunity)
                if self._paper_trader is not None:
                    decision = self._portfolio_risk.apply(
                        decision, self._paper_trader.load(),
                    )
                decisions.append(decision)
                if self._paper_trader is not None:
                    self._paper_trader.record(decision)
        return decisions

    @staticmethod
    def _finish(decisions: list[StrategyDecision]) -> list[StrategyDecision]:

        decisions.sort(
            key=lambda decision: (
                decision.expected_value,
                decision.edge,
            ),
            reverse=True,
        )

        logger.info("Generated %d strategy decisions", len(decisions))

        return decisions
