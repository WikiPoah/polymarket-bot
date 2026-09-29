# File-Version: 1.2.0
"""Chronological, event-cluster-safe forecast dataset splitting."""

from collections import defaultdict
from datetime import datetime

from src.evaluation.models import ForecastObservation, ObservationSplit


def chronological_cluster_split(
    observations: list[ForecastObservation] | tuple[ForecastObservation, ...],
    train_fraction: float = 0.60,
    calibration_fraction: float = 0.20,
) -> ObservationSplit:
    """Assign entire event clusters in order of their first forecast."""
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be between zero and one")
    if not 0.0 <= calibration_fraction < 1.0:
        raise ValueError("calibration_fraction must be between zero and one")
    if train_fraction + calibration_fraction >= 1.0:
        raise ValueError("split fractions must leave a test partition")

    ordered = sorted(
        observations,
        key=lambda item: (item.forecast_timestamp, item.observation_id),
    )
    groups: dict[str, list[ForecastObservation]] = defaultdict(list)
    for observation in observations:
        groups[observation.event_cluster_id].append(observation)
    if not ordered:
        return ObservationSplit((), (), (), ())
    if len(ordered) == 1:
        return ObservationSplit((), (), tuple(ordered), ())
    train_index = min(max(int(len(ordered) * train_fraction), 1), len(ordered) - 1)
    calibration_index = min(
        max(int(len(ordered) * (train_fraction + calibration_fraction)), train_index + 1),
        len(ordered) - 1,
    )
    train_boundary = datetime.fromisoformat(ordered[train_index - 1].forecast_timestamp)
    calibration_boundary = datetime.fromisoformat(
        ordered[calibration_index - 1].forecast_timestamp
    )
    train_clusters: set[str] = set()
    calibration_clusters: set[str] = set()
    test_clusters: set[str] = set()
    excluded_clusters: set[str] = set()
    for cluster, values in groups.items():
        start = min(datetime.fromisoformat(item.forecast_timestamp) for item in values)
        end = max(datetime.fromisoformat(item.forecast_timestamp) for item in values)
        if end <= train_boundary:
            train_clusters.add(cluster)
        elif start > train_boundary and end <= calibration_boundary:
            calibration_clusters.add(cluster)
        elif start > calibration_boundary:
            test_clusters.add(cluster)
        else:
            excluded_clusters.add(cluster)

    def partition(cluster_ids: set[str]) -> tuple[ForecastObservation, ...]:
        return tuple(sorted(
            (item for item in observations if item.event_cluster_id in cluster_ids),
            key=lambda item: (item.forecast_timestamp, item.observation_id),
        ))

    return ObservationSplit(
        partition(train_clusters),
        partition(calibration_clusters),
        partition(test_clusters),
        partition(excluded_clusters),
    )


def optimized_chronological_cluster_split(
    observations: list[ForecastObservation] | tuple[ForecastObservation, ...],
    *,
    minimum_calibration_observations: int = 30,
    minimum_test_observations: int = 100,
    target_train_fraction: float = .60,
    target_calibration_fraction: float = .20,
) -> ObservationSplit:
    """Choose viable chronological boundaries while purging crossing clusters."""
    if minimum_calibration_observations < 1 or minimum_test_observations < 1:
        raise ValueError("minimum split sizes must be positive")
    groups: dict[str, list[ForecastObservation]] = defaultdict(list)
    for observation in observations:
        groups[observation.event_cluster_id].append(observation)
    intervals = [(
        min(datetime.fromisoformat(item.forecast_timestamp) for item in values),
        max(datetime.fromisoformat(item.forecast_timestamp) for item in values),
        len(values),
        cluster,
    ) for cluster, values in groups.items()]
    boundaries = sorted({value for start, end, _, _ in intervals for value in (start, end)})
    best: tuple[tuple[float, ...], datetime, datetime, tuple[set[str], ...]] | None = None
    for index, train_boundary in enumerate(boundaries):
        for calibration_boundary in boundaries[index + 1:]:
            cluster_sets = (set(), set(), set(), set())
            counts = [0, 0, 0, 0]
            for start, end, count, cluster in intervals:
                partition = (
                    0 if end <= train_boundary
                    else 1 if start > train_boundary and end <= calibration_boundary
                    else 2 if start > calibration_boundary
                    else 3
                )
                cluster_sets[partition].add(cluster)
                counts[partition] += count
            if (
                not counts[0]
                or counts[1] < minimum_calibration_observations
                or counts[2] < minimum_test_observations
            ):
                continue
            retained = sum(counts[:3])
            deviation = (
                abs(counts[0] / retained - target_train_fraction)
                + abs(counts[1] / retained - target_calibration_fraction)
            )
            score = (counts[3], deviation, -min(counts[:3]))
            candidate = (score, train_boundary, calibration_boundary, cluster_sets)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        return chronological_cluster_split(
            observations, target_train_fraction, target_calibration_fraction,
        )

    def partition(cluster_ids: set[str]) -> tuple[ForecastObservation, ...]:
        return tuple(sorted(
            (item for item in observations if item.event_cluster_id in cluster_ids),
            key=lambda item: (item.forecast_timestamp, item.observation_id),
        ))

    cluster_sets = best[3]
    return ObservationSplit(*(partition(values) for values in cluster_sets))
