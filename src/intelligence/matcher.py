"""
Utilities for matching geopolitical events to Polymarket markets.
"""

from src.models import (
    GeoPoliticalEvent,
    ScoredEvent,
    TradingOpportunity,
)


def calculate_match_score(
    event: GeoPoliticalEvent,
    market: dict,
) -> int:
    """
    Estimate how closely an event matches a Polymarket market.

    Args:
        event:
            Parsed geopolitical event.

        market:
            Market returned by the Polymarket API.

    Returns:
        Match score between 0 and 100.
    """

    score = 0

    question = market.get("question", "").lower()
    title = event.title.lower()

    if event.country and event.country.lower() in question:
        score += 40

    if event.category.lower() in question:
        score += 20

    keywords = [
        "iran",
        "israel",
        "gaza",
        "palestine",
        "ukraine",
        "russia",
        "china",
        "taiwan",
        "oil",
        "opec",
        "nuclear",
        "missile",
        "war",
        "sanctions",
        "ceasefire",
    ]

    for keyword in keywords:
        if keyword in title and keyword in question:
            score += 10

    return min(score, 100)


def find_matching_markets(
    scored_event: ScoredEvent,
    markets: list[dict],
    minimum_score: int = 40,
) -> list[TradingOpportunity]:
    """
    Find markets matching a scored geopolitical event.

    Args:
        scored_event:
            Event to match.

        markets:
            Candidate Polymarket markets.

        minimum_score:
            Minimum acceptable match score.

    Returns:
        Trading opportunities ordered by match quality.
    """

    opportunities: list[TradingOpportunity] = []

    for market in markets:

        match_score = calculate_match_score(
            scored_event.event,
            market,
        )

        if match_score >= minimum_score:

            opportunities.append(
                TradingOpportunity(
                    event=scored_event,
                    market=market,
                    match_score=match_score,
                )
            )

    opportunities.sort(
        key=lambda opportunity: opportunity.match_score,
        reverse=True,
    )

    return opportunities