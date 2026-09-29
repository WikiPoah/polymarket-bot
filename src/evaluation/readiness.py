# File-Version: 1.2.1
"""Dataset-completeness gates for historical benchmark acceptance."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ProviderCoverage:
    provider: str
    total_partitions: int
    complete_partitions: int
    incomplete_partitions: int
    statuses: dict[str, int]
    intentionally_excluded: bool = False
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class BenchmarkReadiness:
    market_price_coverage_usable: bool
    intelligence_complete: bool
    observation_sample_usable: bool
    category_diversity_usable: bool
    leakage_checks_passed: bool
    split_usable: bool
    ready_to_freeze: bool
    provider_coverage: tuple[ProviderCoverage, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def assess_benchmark_readiness(
    manifest_path: str | Path | list[str | Path],
    *,
    calibration_observations: int,
    test_observations: int,
    minimum_calibration_observations: int = 30,
    minimum_test_observations: int = 100,
    market_price_coverage_percentage: float | None = None,
    observation_count: int | None = None,
    event_cluster_count: int | None = None,
    category_count: int | None = None,
    leakage_violations: int = 0,
    minimum_price_coverage_percentage: float = 95.0,
    minimum_observations: int = 500,
    minimum_event_clusters: int = 30,
    minimum_categories: int = 3,
) -> BenchmarkReadiness:
    """Reject incomplete intelligence plans and statistically unusable splits."""
    blockers: list[str] = []
    coverage: list[ProviderCoverage] = []
    paths = manifest_path if isinstance(manifest_path, list) else [manifest_path]
    partitions = []
    states = {}
    exclusions = {}
    for value in paths:
        try:
            payload = json.loads(Path(value).read_text(encoding="utf-8"))
            partitions.extend(payload["partitions"])
            states.update(payload["collection_status"])
            exclusions.update(payload.get("provider_exclusions", {}))
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            blockers.append(f"historical intelligence manifest is missing or invalid: {value}")

    provider_states: dict[str, Counter[str]] = defaultdict(Counter)
    for partition in partitions:
        partition_id = str(partition.get("partition_id") or "")
        provider = str(partition.get("provider") or "UNKNOWN")
        state = states.get(partition_id, {})
        status = str(state.get("status") or "pending")
        provider_states[provider][status] += 1
    for provider in sorted(provider_states):
        statuses = provider_states[provider]
        total = sum(statuses.values())
        complete = statuses.get("complete", 0)
        incomplete = total - complete
        exclusion = exclusions.get(provider, {})
        intentionally_excluded = bool(exclusion and statuses.get("excluded") == total)
        coverage.append(ProviderCoverage(
            provider=provider,
            total_partitions=total,
            complete_partitions=complete,
            incomplete_partitions=incomplete,
            statuses=dict(sorted(statuses.items())),
            intentionally_excluded=intentionally_excluded,
            exclusion_reason=(str(exclusion.get("reason")) if exclusion else None),
        ))
        if incomplete and not intentionally_excluded:
            blockers.append(
                f"{provider} has {incomplete}/{total} incomplete intelligence partitions"
            )
    if not coverage:
        blockers.append("historical intelligence manifest contains no provider partitions")

    split_usable = (
        calibration_observations >= minimum_calibration_observations
        and test_observations >= minimum_test_observations
    )
    if calibration_observations < minimum_calibration_observations:
        blockers.append(
            f"calibration split has {calibration_observations} observations; "
            f"minimum is {minimum_calibration_observations}"
        )
    if test_observations < minimum_test_observations:
        blockers.append(
            f"test split has {test_observations} observations; minimum is "
            f"{minimum_test_observations}"
        )
    market_price_coverage_usable = (
        market_price_coverage_percentage is not None
        and market_price_coverage_percentage >= minimum_price_coverage_percentage
    )
    if not market_price_coverage_usable:
        blockers.append(
            "usable market-price coverage is missing or below "
            f"{minimum_price_coverage_percentage:.1f}%"
        )
    observation_sample_usable = (
        observation_count is not None
        and observation_count >= minimum_observations
        and event_cluster_count is not None
        and event_cluster_count >= minimum_event_clusters
    )
    if not observation_sample_usable:
        blockers.append(
            f"benchmark requires at least {minimum_observations} observations and "
            f"{minimum_event_clusters} causal event clusters"
        )
    category_diversity_usable = (
        category_count is not None and category_count >= minimum_categories
    )
    if not category_diversity_usable:
        blockers.append(f"benchmark requires at least {minimum_categories} represented categories")
    leakage_checks_passed = leakage_violations == 0
    if not leakage_checks_passed:
        blockers.append(f"benchmark has {leakage_violations} leakage violations")
    active_coverage = [item for item in coverage if not item.intentionally_excluded]
    intelligence_complete = bool(active_coverage) and all(
        item.incomplete_partitions == 0 for item in active_coverage
    )
    return BenchmarkReadiness(
        market_price_coverage_usable=market_price_coverage_usable,
        intelligence_complete=intelligence_complete,
        observation_sample_usable=observation_sample_usable,
        category_diversity_usable=category_diversity_usable,
        leakage_checks_passed=leakage_checks_passed,
        split_usable=split_usable,
        ready_to_freeze=(
            not blockers
            and all((
                market_price_coverage_usable,
                intelligence_complete,
                observation_sample_usable,
                category_diversity_usable,
                leakage_checks_passed,
                split_usable,
            ))
        ),
        provider_coverage=tuple(coverage),
        blockers=tuple(blockers),
    )
