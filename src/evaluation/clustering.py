# File-Version: 1.2.2
"""Deterministic, causal clustering for historical intelligence articles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import re
from urllib.parse import urlsplit

from src.intelligence.classifier import EventClassifier
from src.paper_trading.historical import HistoricalIntelligenceRecord, _parse_time


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "in", "is", "it", "of", "on", "or", "that", "the", "to", "was", "will",
    "with",
}


@dataclass(frozen=True)
class EventClusterAssignment:
    record_id: str
    event_cluster_id: str
    available_at: str
    provider: str
    publisher: str
    event_type: str
    actors: tuple[str, ...]
    countries: tuple[str, ...]
    independent_confirmation_count: int
    confirmation_group_id: str


@dataclass
class _Cluster:
    cluster_id: str
    last_available_at: datetime
    event_type: str
    actors: set[str]
    countries: set[str]
    tokens: set[str]
    publishers: set[str]
    confirmation_signatures: list[set[str]]
    confirmation_publishers: set[str]


def publisher_identity(record: HistoricalIntelligenceRecord) -> str:
    """Prefer the original publisher over the transport provider."""
    if record.publisher:
        return record.publisher.strip().lower()
    hostname = urlsplit(record.source_url).hostname
    if hostname:
        return hostname.removeprefix("www.").lower()
    return (record.provider or record.source or "unknown").strip().lower()


def record_identity(record: HistoricalIntelligenceRecord) -> str:
    """Return the stable collected identity or a deterministic legacy fallback."""
    return record.record_id or hashlib.sha256(
        f"{record.source_url}|{record.title}|{record.available_at}".encode()
    ).hexdigest()


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", value.lower()):
        if len(token) <= 2 or token in _STOP_WORDS:
            continue
        if token.endswith("es") and len(token) > 5:
            token = token[:-2]
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        tokens.add(token)
    return tokens


class CausalEventClusterer:
    """Assign each article using only clusters visible when it became available."""

    def __init__(
        self,
        *,
        maximum_gap: timedelta = timedelta(hours=72),
        minimum_title_similarity: float = 0.45,
    ) -> None:
        self.maximum_gap = maximum_gap
        self.minimum_title_similarity = minimum_title_similarity

    def cluster(
        self,
        records: list[HistoricalIntelligenceRecord]
        | tuple[HistoricalIntelligenceRecord, ...],
    ) -> tuple[EventClusterAssignment, ...]:
        classifier = EventClassifier()
        clusters: list[_Cluster] = []
        assignments: list[EventClusterAssignment] = []
        ordered = sorted(records, key=lambda item: (
            _parse_time(item.available_at), item.record_id or item.source_url, item.title,
        ))
        for record in ordered:
            available_at = max(
                _parse_time(record.available_at), _parse_time(record.published_at),
            )
            event = classifier.classify(record.to_event())
            tokens = _tokens(record.title)
            actors = set(event.actors)
            countries = set(event.countries)
            event_type = event.event_type.name
            candidates: list[tuple[float, _Cluster]] = []
            for cluster in clusters:
                if available_at - cluster.last_available_at > self.maximum_gap:
                    continue
                if (
                    event_type != cluster.event_type
                    and "OTHER" not in {event_type, cluster.event_type}
                ):
                    continue
                union = tokens | cluster.tokens
                similarity = len(tokens & cluster.tokens) / len(union) if union else 0.0
                entity_match = bool(
                    (actors and actors & cluster.actors)
                    or (countries and countries & cluster.countries)
                )
                if entity_match and similarity >= self.minimum_title_similarity:
                    candidates.append((similarity, cluster))
            cluster = max(candidates, key=lambda item: (item[0], item[1].cluster_id))[1] \
                if candidates else None
            publisher = publisher_identity(record)
            if cluster is None:
                seed = "|".join((
                    available_at.isoformat(), event_type,
                    ",".join(sorted(actors)), ",".join(sorted(countries)),
                    " ".join(sorted(tokens)), record.record_id or record.source_url,
                ))
                cluster = _Cluster(
                    cluster_id=f"event-{hashlib.sha256(seed.encode()).hexdigest()[:16]}",
                    last_available_at=available_at,
                    event_type=event_type,
                    actors=set(actors),
                    countries=set(countries),
                    tokens=set(tokens),
                    publishers={publisher},
                    confirmation_signatures=[set(tokens)],
                    confirmation_publishers={publisher},
                )
                clusters.append(cluster)
                confirmation_index = 0
            else:
                cluster.last_available_at = available_at
                cluster.actors.update(actors)
                cluster.countries.update(countries)
                cluster.tokens.update(tokens)
                cluster.publishers.add(publisher)
                similarities = [
                    len(tokens & signature) / len(tokens | signature)
                    if tokens | signature else 0.0
                    for signature in cluster.confirmation_signatures
                ]
                closest = max(range(len(similarities)), key=similarities.__getitem__)
                if publisher in cluster.confirmation_publishers or similarities[closest] >= .55:
                    confirmation_index = closest
                else:
                    confirmation_index = len(cluster.confirmation_signatures)
                    cluster.confirmation_signatures.append(tokens)
                    cluster.confirmation_publishers.add(publisher)
            assignments.append(EventClusterAssignment(
                record_id=record_identity(record),
                event_cluster_id=cluster.cluster_id,
                available_at=available_at.isoformat(),
                provider=record.provider or record.source,
                publisher=publisher,
                event_type=event_type,
                actors=tuple(sorted(actors)),
                countries=tuple(sorted(countries)),
                independent_confirmation_count=len(cluster.confirmation_signatures),
                confirmation_group_id=f"{cluster.cluster_id}:report-{confirmation_index}",
            ))
        return tuple(assignments)
