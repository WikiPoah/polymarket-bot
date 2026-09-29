# File-Version: 1.0.0
"""Bot-versus-market probabilistic forecast metrics."""

import math
import random
from collections import defaultdict
from typing import Callable, Iterable

from src.evaluation.models import (
    BootstrapInterval,
    EvaluationMetrics,
    EvaluationReport,
    ForecastObservation,
)


class ForecastEvaluator:
    """Evaluate resolved forecasts against the contemporaneous market baseline."""

    def evaluate(
        self,
        observations: Iterable[ForecastObservation],
        bootstrap_samples: int = 1000,
        bootstrap_seed: int = 0,
    ) -> EvaluationReport:
        resolved = tuple(item for item in observations if item.resolved_yes is not None)
        breakdowns = {
            "category": self._breakdown(resolved, lambda item: item.category),
            "time_to_resolution": self._breakdown(resolved, self._time_bucket),
            "confirmation": self._breakdown(
                resolved,
                lambda item: "INDEPENDENTLY_CONFIRMED"
                if item.independently_confirmed else "SINGLE_SOURCE",
            ),
            "confidence": self._breakdown(resolved, self._confidence_bucket),
            "source": self._source_breakdown(resolved),
        }
        interval = self._cluster_bootstrap(
            resolved, bootstrap_samples, bootstrap_seed,
        ) if bootstrap_samples > 0 else None
        return EvaluationReport(self._metrics(resolved), breakdowns, interval)

    def _metrics(self, values: Iterable[ForecastObservation]) -> EvaluationMetrics:
        observations = tuple(values)
        if not observations:
            return EvaluationMetrics(0, 0, 0, None, None, None, None, None, None, None)
        outcomes = [1.0 if item.resolved_yes else 0.0 for item in observations]
        bot_brier = self._mean(
            (item.bot_probability - outcome) ** 2
            for item, outcome in zip(observations, outcomes)
        )
        market_brier = self._mean(
            (item.market_probability - outcome) ** 2
            for item, outcome in zip(observations, outcomes)
        )
        bot_log = self._mean(
            self._log_loss(item.bot_probability, outcome)
            for item, outcome in zip(observations, outcomes)
        )
        market_log = self._mean(
            self._log_loss(item.market_probability, outcome)
            for item, outcome in zip(observations, outcomes)
        )
        return EvaluationMetrics(
            sample_count=len(observations),
            unique_market_count=len({item.market_id for item in observations}),
            unique_event_cluster_count=len({item.event_cluster_id for item in observations}),
            bot_brier_score=bot_brier,
            market_brier_score=market_brier,
            brier_improvement=market_brier - bot_brier,
            bot_log_loss=bot_log,
            market_log_loss=market_log,
            log_loss_improvement=market_log - bot_log,
            calibration_error=self._calibration_error(observations),
        )

    def _breakdown(
        self,
        observations: tuple[ForecastObservation, ...],
        key: Callable[[ForecastObservation], str],
    ) -> dict[str, EvaluationMetrics]:
        groups: dict[str, list[ForecastObservation]] = defaultdict(list)
        for observation in observations:
            groups[key(observation)].append(observation)
        return {name: self._metrics(values) for name, values in sorted(groups.items())}

    def _source_breakdown(
        self, observations: tuple[ForecastObservation, ...],
    ) -> dict[str, EvaluationMetrics]:
        groups: dict[str, list[ForecastObservation]] = defaultdict(list)
        for observation in observations:
            for source in observation.supporting_sources or (observation.source,):
                groups[source].append(observation)
        return {name: self._metrics(values) for name, values in sorted(groups.items())}

    def _cluster_bootstrap(
        self,
        observations: tuple[ForecastObservation, ...],
        samples: int,
        seed: int,
    ) -> BootstrapInterval:
        groups: dict[str, list[ForecastObservation]] = defaultdict(list)
        for observation in observations:
            groups[observation.event_cluster_id].append(observation)
        cluster_ids = sorted(groups)
        if not cluster_ids:
            return BootstrapInterval(samples, 0.95, None, None)
        generator = random.Random(seed)
        improvements = []
        for _ in range(samples):
            selected = [generator.choice(cluster_ids) for _ in cluster_ids]
            values = [item for cluster in selected for item in groups[cluster]]
            metric = self._metrics(values)
            if metric.brier_improvement is not None:
                improvements.append(metric.brier_improvement)
        improvements.sort()
        return BootstrapInterval(
            samples=samples,
            confidence_level=0.95,
            lower=self._percentile(improvements, 0.025),
            upper=self._percentile(improvements, 0.975),
        )

    @staticmethod
    def _log_loss(probability: float, outcome: float) -> float:
        value = min(max(probability, 1e-15), 1.0 - 1e-15)
        return -(outcome * math.log(value) + (1.0 - outcome) * math.log(1.0 - value))

    @staticmethod
    def _calibration_error(observations: tuple[ForecastObservation, ...]) -> float:
        bins: dict[int, list[ForecastObservation]] = defaultdict(list)
        for observation in observations:
            bins[min(int(observation.bot_probability * 10), 9)].append(observation)
        total = len(observations)
        return sum(
            len(values) / total * abs(
                sum(item.bot_probability for item in values) / len(values)
                - sum(bool(item.resolved_yes) for item in values) / len(values)
            )
            for values in bins.values()
        )

    @staticmethod
    def _time_bucket(observation: ForecastObservation) -> str:
        seconds = observation.evaluation_time_to_resolution_seconds
        if seconds is None:
            return "UNKNOWN"
        days = seconds / 86400
        if days <= 1:
            return "0-1_DAY"
        if days <= 7:
            return "1-7_DAYS"
        if days <= 30:
            return "7-30_DAYS"
        if days <= 90:
            return "30-90_DAYS"
        return "90+_DAYS"

    @staticmethod
    def _confidence_bucket(observation: ForecastObservation) -> str:
        value = float(observation.provenance.get("strategy_confidence", 0.0))
        if value < 0.6:
            return "LOW"
        if value < 0.8:
            return "MEDIUM"
        return "HIGH"

    @staticmethod
    def _mean(values: Iterable[float]) -> float:
        items = list(values)
        return sum(items) / len(items)

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        position = (len(values) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        weight = position - lower
        return values[lower] * (1.0 - weight) + values[upper] * weight
