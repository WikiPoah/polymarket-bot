"""
Market filtering utilities.

This module contains reusable functions for filtering Polymarket
markets based on the trading bot's area of interest.
"""

import re

from src.config import GEOPOLITICAL_KEYWORDS


def is_geopolitical_market(market):
    """
    Determine whether a market is relevant to the trading strategy.

    A market is considered relevant if one of the configured
    geopolitical keywords appears in the market question or
    the title of one of its associated events.

    Args:
        market (dict):
            A market returned by the Polymarket API.

    Returns:
        bool:
            True if the market matches at least one keyword.
    """

    # Start with the market question
    search_text = market.get("question", "")

    # Include the titles of any associated events
    events = market.get("events", [])

    for event in events:
        search_text += f" {event.get('title', '')}"

    search_text = search_text.lower()

    # Check for whole-word keyword matches
    for keyword in GEOPOLITICAL_KEYWORDS:
        pattern = r"\b" + re.escape(keyword.lower()) + r"\b"

        if re.search(pattern, search_text):
            return True

    return False


def filter_geopolitical_markets(markets):
    """
    Filter a list of markets to retain only geopolitical ones.

    Args:
        markets (list[dict]):
            Markets returned by the API.

    Returns:
        list[dict]:
            Only markets matching the configured keywords.
    """

    return [
        market
        for market in markets
        if is_geopolitical_market(market)
    ]