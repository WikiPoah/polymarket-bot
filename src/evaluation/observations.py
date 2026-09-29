# File-Version: 1.6.0
"""Generate deterministic forecasts from historical market and evidence state."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Mapping

from src.evaluation.models import ForecastObservation
from src.evaluation.clustering import CausalEventClusterer, record_identity
from src.intelligence.client import IntelligenceClient
from src.intelligence.pipeline import IntelligencePipeline
from src.intelligence.providers.base import IntelligenceProvider
from src.models import GeoPoliticalEvent
from src.paper_trading.historical import (
    HistoricalIntelligenceRecord,
    HistoricalMarketSnapshot,
    _parse_time,
)


def _digest(*values: object) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _event_identity(title: str, url: str) -> str:
    normalized_url = url.strip().lower()
    normalized_title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return normalized_url or normalized_title


class _VisibleHistoricalProvider(IntelligenceProvider):
    """Expose a pre-indexed immutable historical evidence view."""

    def __init__(self, events: tuple[GeoPoliticalEvent, ...]) -> None:
        self.events = events

    def fetch(self, query=None, limit=100, sort="recent") -> list[GeoPoliticalEvent]:
        return [deepcopy(item) for item in self.events[:limit]]


class ForecastObservationGenerator:
    """Run the unchanged strategy at each snapshot without future information."""

    def generate(
        self,
        snapshots: list[HistoricalMarketSnapshot] | tuple[HistoricalMarketSnapshot, ...],
        intelligence: list[HistoricalIntelligenceRecord]
        | tuple[HistoricalIntelligenceRecord, ...],
        market_clusters: Mapping[str, str] | None = None,
    ) -> list[ForecastObservation]:
        clusters = dict(market_clusters or {})
        ordered = sorted(snapshots, key=lambda item: (_parse_time(item.observed_at), item.market_id))
        evidence = sorted(
            intelligence,
            key=lambda item: max(_parse_time(item.available_at), _parse_time(item.published_at)),
        )
        assignments = {
            item.record_id: item
            for item in CausalEventClusterer().cluster(tuple(evidence))
        }
        seen_states: set[tuple[str, str]] = set()
        evaluated_versions: dict[str, int] = {}
        visible_clusters: dict[str, list[GeoPoliticalEvent]] = {}
        evidence_cluster_ids: list[str] = []
        evidence_index = 0
        observations: list[ForecastObservation] = []
        classified_cache: dict[
            tuple[int, datetime], tuple[GeoPoliticalEvent, ...]
        ] = {}

        for snapshot in ordered:
            forecast_at = _parse_time(snapshot.observed_at)
            while evidence_index < len(evidence):
                record = evidence[evidence_index]
                visible_at = max(
                    _parse_time(record.available_at),
                    _parse_time(record.published_at),
                )
                if visible_at > forecast_at:
                    break
                assignment = assignments[record_identity(record)]
                event = record.to_event()
                event.event_cluster_id = assignment.event_cluster_id
                event.provider = assignment.provider
                event.publisher = assignment.publisher
                event.confirmation_group_id = assignment.confirmation_group_id
                visible_clusters.setdefault(assignment.event_cluster_id, []).append(event)
                evidence_cluster_ids.append(assignment.event_cluster_id)
                evidence_index += 1
            previous_market_index = evaluated_versions.get(snapshot.market_id, 0)
            if previous_market_index == evidence_index:
                continue
            evaluated_versions[snapshot.market_id] = evidence_index
            changed_clusters = tuple(sorted(set(
                evidence_cluster_ids[previous_market_index:evidence_index]
            )))
            visible_events = tuple(sorted(
                (
                    event
                    for cluster_id in changed_clusters
                    for event in visible_clusters[cluster_id]
                ),
                key=lambda event: event.published_at,
                reverse=True,
            )[:100])
            cache_key = (
                int(_digest(changed_clusters)[:12], 16),
                forecast_at,
            )
            classified_events = classified_cache.get(cache_key)
            client = IntelligenceClient(
                [_VisibleHistoricalProvider(visible_events)], evidence_time=forecast_at,
            )
            pipeline = IntelligencePipeline(client, as_of=forecast_at)
            if classified_events is None:
                fetched = client.fetch(query="historical-replay", limit=100)
                classified_events = pipeline.classify_events(fetched)
                classified_cache[cache_key] = classified_events
            decisions = pipeline.run_classified_events(
                [snapshot.to_market()], classified_events,
            )

            for decision in decisions:
                event = decision.opportunity.event.event
                available_at = event.available_at or event.published_at
                available_at = self._utc(available_at)
                published_at = self._utc(event.published_at)
                if available_at > forecast_at or published_at > forecast_at:
                    raise ValueError("forecast attempted to use future intelligence")

                sources = tuple(sorted(set(event.supporting_sources or [
                    event.publisher or event.source,
                ])))
                evidence_state_id = _digest(
                    event.event_cluster_id or _event_identity(event.title, event.source_url),
                    available_at.isoformat(),
                    sources,
                    round(event.evidence_confidence, 12),
                )
                state_key = (snapshot.market_id, evidence_state_id)
                if state_key in seen_states:
                    continue
                seen_states.add(state_key)

                cluster_id = clusters.get(snapshot.market_id, snapshot.market_id)
                observation_id = _digest(
                    snapshot.market_id,
                    cluster_id,
                    evidence_state_id,
                    forecast_at.isoformat(),
                )
                resolved_at = (
                    _parse_time(snapshot.resolved_at)
                    if snapshot.resolved_at is not None else None
                )
                time_to_resolution = (
                    (resolved_at - forecast_at).total_seconds()
                    if resolved_at is not None else None
                )
                if time_to_resolution is not None and time_to_resolution <= 0:
                    raise ValueError("forecast timestamp must precede resolution")

                observations.append(ForecastObservation(
                    observation_id=observation_id,
                    market_id=snapshot.market_id,
                    event_cluster_id=cluster_id,
                    evidence_state_id=evidence_state_id,
                    forecast_timestamp=forecast_at.isoformat(),
                    evidence_available_at=available_at.isoformat(),
                    evidence_published_at=published_at.isoformat(),
                    # The benchmark is always against the observed YES price.
                    # Strategy outcome-label fallbacks must not alter the baseline.
                    market_probability=snapshot.yes_price,
                    bot_probability=decision.estimated_probability,
                    # Labels are attached only after the production forecast returned.
                    resolved_yes=snapshot.resolved_yes,
                    resolved_at=resolved_at.isoformat() if resolved_at is not None else None,
                    evaluation_time_to_resolution_seconds=time_to_resolution,
                    category=str(snapshot.category or "OTHER"),
                    event_type=event.event_type.name,
                    expected_outcome=decision.opportunity.expected_outcome.name,
                    match_score=decision.opportunity.match_score,
                    event_score=decision.opportunity.event.score,
                    relevance_confidence=decision.opportunity.confidence,
                    evidence_confidence=event.evidence_confidence,
                    evidence_recency_seconds=max(
                        0.0, (forecast_at - available_at).total_seconds()
                    ),
                    source=event.source,
                    supporting_sources=sources,
                    independent_confirmation_count=len(sources),
                    independently_confirmed=len(sources) > 1,
                    liquidity=snapshot.liquidity,
                    volume=snapshot.volume,
                    is_new_evidence=True,
                    event_title=event.title,
                    event_url=event.source_url,
                    match_reasons=tuple(decision.opportunity.match_reasons),
                    provenance={
                        "availability_policy": "provider.available_at",
                        "event_cluster_policy": (
                            "provided_cluster"
                            if snapshot.market_id in clusters else "market_id_fallback"
                        ),
                        "confirmation_policy": "distinct_original_publishers",
                        "market_observed_at": snapshot.observed_at,
                        "event_source": event.source,
                        "event_provider": event.provider or event.source,
                        "event_publisher": event.publisher or event.source,
                        "evidence_event_cluster_id": event.event_cluster_id,
                        "event_freshness_score": event.freshness_score,
                        "strategy_action": decision.action.value,
                        "strategy_confidence": decision.confidence,
                    },
                ))

        return observations

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
