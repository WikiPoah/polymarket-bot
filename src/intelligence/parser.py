"""
Utilities for converting intelligence provider responses into
application models.
"""

from datetime import datetime

from src.models import GeoPoliticalEvent

from src.intelligence.exceptions import (
    IntelligenceParsingError,
)


def parse_gdelt_event(
    event: dict,
) -> GeoPoliticalEvent:
    """
    Convert a raw GDELT event into a GeoPoliticalEvent.

    Args:
        event:
            Raw event returned by GDELT.

    Returns:
        A GeoPoliticalEvent instance.

    Raises:
        IntelligenceParsingError:
            If the event is missing required fields.
    """

    try:
        geo = event["geo"]
        metrics = event["metrics"]

        return GeoPoliticalEvent(
            title=event["title"],
            summary=event["summary"],
            category=event["category"],
            subcategory=event["subcategory"],
            country=geo.get("country"),
            region=geo.get("region"),
            continent=geo.get("continent"),
            significance=metrics["significance"],
            confidence=metrics["confidence"],
            market_sensitivity=metrics["market_sensitivity"],
            source_url=event["url"],
            published_at=datetime.fromisoformat(
                event["processed_at"].replace("Z", "+00:00")
            ),
            source="GDELT",
        )

    except KeyError as error:
        raise IntelligenceParsingError(
            f"Missing required GDELT field: {error}"
        ) from error
