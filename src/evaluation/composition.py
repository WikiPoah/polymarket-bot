# File-Version: 1.0.0
"""Composition diagnostics for deciding whether a benchmark is representative."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.evaluation.models import ForecastObservation


@dataclass(frozen=True)
class CompositionReport:
    observation_count: int
    distributions: dict[str, dict[str, int]]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "observation_count": self.observation_count,
            "distributions": self.distributions,
            "warnings": list(self.warnings),
        }


def _time_bucket(seconds: float | None) -> str:
    if seconds is None:
        return "UNKNOWN"
    hours = seconds / 3600
    if hours < 1:
        return "<1_HOUR"
    if hours < 6:
        return "1-6_HOURS"
    if hours < 24:
        return "6-24_HOURS"
    if hours < 72:
        return "1-3_DAYS"
    if hours < 168:
        return "3-7_DAYS"
    return "7+_DAYS"


def _confidence_bucket(value: float) -> str:
    if value < .6:
        return "LOW"
    if value < .8:
        return "MEDIUM"
    return "HIGH"


def _probability_bucket(value: float) -> str:
    lower = min(int(value * 10), 9) * 10
    return f"{lower:02d}-{lower + 10:02d}%"


def analyze_composition(
    observations: list[ForecastObservation] | tuple[ForecastObservation, ...],
) -> CompositionReport:
    counters: dict[str, Counter[str]] = {
        name: Counter() for name in (
            "category", "provider", "publisher", "event_cluster", "confidence",
            "confirmation_count", "time_to_resolution", "market", "resolved_outcome",
            "market_probability",
        )
    }
    for item in observations:
        counters["category"][item.category] += 1
        counters["provider"][str(item.provenance.get("event_provider") or item.source)] += 1
        counters["publisher"][str(item.provenance.get("event_publisher") or item.source)] += 1
        counters["event_cluster"][str(
            item.provenance.get("evidence_event_cluster_id") or "UNAVAILABLE"
        )] += 1
        confidence = float(item.provenance.get("strategy_confidence", 0.0))
        counters["confidence"][_confidence_bucket(confidence)] += 1
        counters["confirmation_count"][str(item.independent_confirmation_count)] += 1
        counters["time_to_resolution"][_time_bucket(
            item.evaluation_time_to_resolution_seconds,
        )] += 1
        counters["market"][item.market_id] += 1
        counters["resolved_outcome"][
            "YES" if item.resolved_yes else "NO" if item.resolved_yes is False else "UNKNOWN"
        ] += 1
        counters["market_probability"][_probability_bucket(item.market_probability)] += 1

    total = len(observations)
    warnings: list[str] = []
    if total:
        for dimension in ("category", "provider", "publisher", "confidence"):
            largest = max(counters[dimension].values(), default=0)
            if largest / total >= .8:
                value = counters[dimension].most_common(1)[0][0]
                warnings.append(
                    f"{dimension} is concentrated: {value} represents {largest / total:.1%}."
                )
        near_close = sum(
            count for bucket, count in counters["time_to_resolution"].items()
            if bucket in {"<1_HOUR", "1-6_HOURS", "6-24_HOURS"}
        )
        if near_close / total >= .8:
            warnings.append(f"{near_close / total:.1%} of observations are under one day from resolution.")
    return CompositionReport(
        observation_count=total,
        distributions={
            name: dict(sorted(values.items())) for name, values in counters.items()
        },
        warnings=tuple(warnings),
    )
