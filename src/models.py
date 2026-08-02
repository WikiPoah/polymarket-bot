"""
Application data models.

This module defines the core data structures used throughout the
application. These models provide a consistent interface between
different parts of the system.
"""

from dataclasses import dataclass, field
from datetime import datetime

from src.intelligence.classification import (
    EventType,
    Region,
    Topic,
)
from src.intelligence.outcomes import Outcome


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
    source: str = ""
    source_reliability: float = 0.50
    evidence_confidence: float = 0.50

    event_type: EventType = EventType.OTHER
    outcome: Outcome = Outcome.OTHER
    classified_region: Region = Region.UNKNOWN

    topics: list[Topic] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    supporting_sources: list[str] = field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        """Number of independent sources supporting this event."""

        return len(self.supporting_sources) or 1

    @property
    def supporting_source_count(self) -> int:
        """Compatibility alias for the supporting-source count."""

        return self.evidence_count

    @property
    def source_confidence(self) -> float:
        """Alias for the combined evidence confidence."""

        return self.evidence_confidence


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
    """

    event: ScoredEvent
    market: dict

    match_score: int
    confidence: float

    match_reasons: list[str] = field(default_factory=list)
    expected_outcome: Outcome = Outcome.OTHER


@dataclass(slots=True)
class ClassifiedMarket:
    """
    Represents a classified Polymarket market.
    """

    market: dict

    event_type: EventType = EventType.OTHER
    expected_outcome: Outcome = Outcome.OTHER
    classified_region: Region = Region.UNKNOWN

    topics: list[Topic] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
