"""
Utilities for matching geopolitical events to classified
Polymarket markets.
"""

from src.intelligence.classification import EventType, Region
from src.intelligence.outcomes import Outcome
from src.models import (
    ClassifiedMarket,
    GeoPoliticalEvent,
    ScoredEvent,
    TradingOpportunity,
)


def calculate_match_score(
    event: GeoPoliticalEvent,
    market: ClassifiedMarket,
) -> tuple[int, float, list[str]]:
    """
    Estimate how closely an event matches a classified market.
    """

    score = 0
    reasons: list[str] = []

    #
    # Leadership markets require relevant evidence.
    #

    if market.event_type == EventType.LEADERSHIP:

        country_match = any(
            country in market.countries
            for country in event.countries
        )

        actor_match = any(
            actor in market.actors
            for actor in event.actors
        )

        ccp_match = (
            "Xi Jinping" in market.actors
            and "China" in market.countries
            and "CCP" in event.actors
        )

        if not (
            event.event_type == EventType.LEADERSHIP
            and (
                actor_match
                or ccp_match
                or country_match
            )
        ):
            return 0, 0.0, []

    #
    # Countries
    #

    for country in event.countries:
        if country in market.countries:
            score += 25
            reasons.append(
                f"Country: {country} (+25)"
            )

    #
    # Outcome
    #

    if (
        event.outcome != Outcome.OTHER
        and event.outcome == market.expected_outcome
    ):
        score += 30
        reasons.append(
            f"Outcome: {event.outcome.name} (+30)"
        )

    #
    # Event type
    #

    if (
        event.event_type != EventType.OTHER
        and event.event_type == market.event_type
    ):
        score += 15
        reasons.append(
            f"Event Type: {event.event_type.name} (+15)"
        )

    #
    # Region
    #

    if (
        event.classified_region != Region.UNKNOWN
        and event.classified_region == market.classified_region
    ):
        score += 10
        reasons.append(
            f"Region: {event.classified_region.name} (+10)"
        )

    #
    # Topics
    #

    for topic in event.topics:
        if topic in market.topics:
            score += 5
            reasons.append(
                f"Topic: {topic.name} (+5)"
            )

    #
    # Actors
    #

    ccp_match = (
        market.event_type == EventType.LEADERSHIP
        and "Xi Jinping" in market.actors
        and "China" in market.countries
        and "CCP" in event.actors
    )

    for actor in event.actors:
        if actor in market.actors:
            score += 20
            reasons.append(
                f"Actor: {actor} (+20)"
            )

    if ccp_match:
        score += 20
        reasons.append(
            "Actor: CCP (+20)"
        )

    score = min(score, 100)

    confidence = round(score / 100, 2)

    return score, confidence, reasons


def find_matching_markets(
    scored_event: ScoredEvent,
    markets: list[ClassifiedMarket],
    minimum_score: int = 30,
) -> list[TradingOpportunity]:
    """
    Find classified markets matching a scored event.
    """

    opportunities: list[TradingOpportunity] = []

    for market in markets:

        (
            match_score,
            confidence,
            reasons,
        ) = calculate_match_score(
            scored_event.event,
            market,
        )

        if match_score >= minimum_score:

            opportunities.append(
                TradingOpportunity(
                    event=scored_event,
                    market=market.market,
                    match_score=match_score,
                    confidence=confidence,
                    match_reasons=reasons,
                    expected_outcome=market.expected_outcome,
                )
            )

    opportunities.sort(
        key=lambda opportunity: (
            opportunity.match_score,
            opportunity.event.score,
        ),
        reverse=True,
    )

    return opportunities
