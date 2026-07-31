"""
Filtering utilities.

This module contains reusable functions for filtering both Polymarket
markets and intelligence events based on the trading bot's area of
interest.
"""

import re

from src.config import GEOPOLITICAL_KEYWORDS


def _contains_keyword(text: str) -> bool:
    """
    Determine whether the supplied text contains one of the configured
    geopolitical keywords.

    Args:
        text:
            Text to search.

    Returns:
        True if at least one keyword is found.
    """

    text = text.lower()

    for keyword in GEOPOLITICAL_KEYWORDS:
        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"

        if re.search(pattern, text):
            return True

    return False


def is_geopolitical_market(market: dict) -> bool:
    """
    Determine whether a market is relevant to the trading strategy.

    Args:
        market:
            A market returned by the Polymarket API.

    Returns:
        True if the market matches at least one keyword.
    """

    search_text = market.get("question", "")

    events = market.get("events", [])

    for event in events:
        search_text += f" {event.get('title', '')}"

    return _contains_keyword(search_text)


def filter_geopolitical_markets(
    markets: list[dict]
) -> list[dict]:
    """
    Filter a list of markets.

    Args:
        markets:
            Markets returned by the Polymarket API.

    Returns:
        Only geopolitical markets.
    """

    return [
        market
        for market in markets
        if is_geopolitical_market(market)
    ]


def is_relevant_event(event: dict) -> bool:
    """
    Determine whether a GDELT event is relevant.

    The filter examines both structured geographic information and
    descriptive text.

    Args:
        event:
            Raw event returned by GDELT.

    Returns:
        True if the event is considered relevant.
    """

    geo = event.get("geo", {})

    search_text = " ".join(
        filter(
            None,
            [
                event.get("title"),
                event.get("summary"),
                event.get("category"),
                event.get("subcategory"),
                geo.get("country"),
                geo.get("region"),
                geo.get("continent"),
            ],
        )
    )

    return _contains_keyword(search_text)


def filter_relevant_events(
    events: list[dict]
) -> list[dict]:
    """
    Filter a list of intelligence events.

    Args:
        events:
            Raw GDELT events.

    Returns:
        Only events relevant to the trading bot.
    """

    return [
        event
        for event in events
        if is_relevant_event(event)
    ]