"""
Application data models.

This module defines the core data structures used throughout the
application. These models provide a consistent interface between
different parts of the system.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Article:
    """
    Represents a news article from any supported intelligence provider.
    """

    title: str
    source: str
    url: str
    published_at: datetime
    summary: str | None = None


@dataclass(slots=True)
class GeoPoliticalEvent:
    """
    Represents a geopolitical event used by the trading bot.

    This model is independent of the underlying intelligence provider.
    """

    title: str
    summary: str

    category: str
    subcategory: str

    country: str | None
    region: str | None
    continent: str | None

    significance: float | None
    confidence: float | None
    market_sensitivity: float | None

    source_url: str
    published_at: datetime


@dataclass(slots=True)
class ScoredEvent:
    """
    Represents a geopolitical event together with its
    calculated relevance score.
    """

    event: GeoPoliticalEvent
    score: int


@dataclass(slots=True)
class TradingOpportunity:
    """
    Represents a potential trading opportunity.

    A trading opportunity links one scored geopolitical event
    to one Polymarket market together with the confidence that
    they are related.
    """

    event: ScoredEvent
    market: dict
    match_score: int