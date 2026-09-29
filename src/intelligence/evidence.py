# File-Version: 1.2.0
"""
Source reliability and cross-provider evidence aggregation.
"""

import re
from datetime import datetime, timezone

from src.config import SOURCE_RELIABILITY
from src.models import GeoPoliticalEvent


def get_source_reliability(source: str) -> float:
    """Return the configured reliability for a source name."""

    return SOURCE_RELIABILITY.get(
        source,
        SOURCE_RELIABILITY["default"],
    )


def get_freshness_score(
    published_at: datetime | None,
    now: datetime | None = None,
) -> float:
    """Score recency with conservative decay for old or undated reports."""
    if not isinstance(published_at, datetime):
        return 0.50
    now = now or datetime.now(timezone.utc)
    published = (
        published_at.replace(tzinfo=timezone.utc)
        if published_at.tzinfo is None
        else published_at.astimezone(timezone.utc)
    )
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    if age_hours <= 6:
        return 1.0
    if age_hours <= 24:
        return 0.90
    if age_hours <= 72:
        return 0.75
    if age_hours <= 168:
        return 0.55
    return 0.35


def _event_keys(event: GeoPoliticalEvent) -> list[str]:
    """Build URL and normalized-title keys for duplicate articles."""

    keys: list[str] = []

    if event.event_cluster_id:
        keys.append(f"cluster:{event.event_cluster_id}")

    if event.source_url:
        keys.append(
            f"url:{event.source_url.strip().lower()}"
        )

    title = re.sub(
        r"[^a-z0-9]+",
        " ",
        event.title.lower(),
    ).strip()

    if title:
        keys.append(f"title:{title}")

    return keys or ["title:"]


def _prepare_event(
    event: GeoPoliticalEvent,
    now: datetime | None = None,
) -> None:
    """Initialize source evidence metadata on a provider event."""

    source = event.source or event.category or "unknown"
    evidence_source = event.confirmation_group_id or event.publisher or source
    event.source_reliability = get_source_reliability(source)
    event.freshness_score = get_freshness_score(event.published_at, now)
    event.evidence_confidence = (
        event.source_reliability * event.freshness_score
    )

    if not event.supporting_sources:
        event.supporting_sources.append(evidence_source)


def _merge_event(
    target: GeoPoliticalEvent,
    duplicate: GeoPoliticalEvent,
) -> None:
    """Merge independent source evidence into the retained event."""

    source = (
        duplicate.confirmation_group_id
        or duplicate.publisher
        or duplicate.source
        or duplicate.category
        or "unknown"
    )

    if source in target.supporting_sources:
        return

    target.supporting_sources.append(source)
    if duplicate.available_at is not None and (
        target.available_at is None
        or duplicate.available_at > target.available_at
    ):
        target.available_at = duplicate.available_at
    target.evidence_confidence = min(
        1.0,
        1.0
        - (
            (1.0 - target.evidence_confidence)
            * (1.0 - duplicate.source_reliability)
        ),
    )


def aggregate_events(
    events: list[GeoPoliticalEvent],
    now: datetime | None = None,
) -> list[GeoPoliticalEvent]:
    """Deduplicate provider events and merge independent evidence."""

    aggregated: list[GeoPoliticalEvent] = []
    by_key: dict[str, GeoPoliticalEvent] = {}

    for event in events:
        _prepare_event(event, now)
        keys = _event_keys(event)
        existing = next(
            (
                by_key[key]
                for key in keys
                if key in by_key
            ),
            None,
        )

        if existing is None:
            for key in keys:
                by_key[key] = event
            aggregated.append(event)
            continue

        _merge_event(existing, event)

    return aggregated
