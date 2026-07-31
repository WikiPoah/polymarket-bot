"""
Utilities for scoring geopolitical events.

This module assigns each geopolitical event a relevance score
used by the trading strategy.
"""

from src.models import (
    GeoPoliticalEvent,
    ScoredEvent,
)

HIGH_PRIORITY_COUNTRIES = {
    "Iran",
    "Israel",
    "Palestine",
    "Russia",
    "Ukraine",
    "China",
    "Taiwan",
}

MEDIUM_PRIORITY_COUNTRIES = {
    "Lebanon",
    "Syria",
    "Jordan",
    "Iraq",
    "Yemen",
    "Saudi Arabia",
    "United Arab Emirates",
    "Turkey",
    "Belarus",
}

HIGH_PRIORITY_KEYWORDS = {
    "missile",
    "strike",
    "attack",
    "war",
    "military",
    "drone",
    "nuclear",
    "sanctions",
    "ceasefire",
    "hostages",
    "hamas",
    "hezbollah",
    "houthi",
    "iran",
    "israel",
    "gaza",
    "ukraine",
    "russia",
    "taiwan",
    "china",
    "opec",
    "oil",
}

HIGH_PRIORITY_CATEGORIES = {
    "Explosions/Remote violence",
    "Violence against civilians",
    "Strategic developments",
}


def score_event(
    event: GeoPoliticalEvent,
) -> ScoredEvent:
    """
    Score a geopolitical event.
    """

    score = 0

    if event.country in HIGH_PRIORITY_COUNTRIES:
        score += 30

    elif event.country in MEDIUM_PRIORITY_COUNTRIES:
        score += 20

    if event.category in HIGH_PRIORITY_CATEGORIES:
        score += 25

    title = event.title.lower()

    for keyword in HIGH_PRIORITY_KEYWORDS:
        if keyword in title:
            score += 10

    if (
        event.market_sensitivity is not None
        and event.market_sensitivity >= 0.75
    ):
        score += 15

    if (
        event.significance is not None
        and event.significance >= 0.75
    ):
        score += 10

    if (
        event.confidence is not None
        and event.confidence >= 0.75
    ):
        score += 10

    score = min(score, 100)

    return ScoredEvent(
        event=event,
        score=score,
    )


def score_events(
    events: list[GeoPoliticalEvent],
) -> list[ScoredEvent]:
    """
    Score and sort events.
    """

    scored = [
        score_event(event)
        for event in events
    ]

    scored.sort(
        key=lambda event: event.score,
        reverse=True,
    )

    return scored