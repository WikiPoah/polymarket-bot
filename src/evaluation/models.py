# File-Version: 1.2.0
"""Data contracts for leakage-safe forecast evaluation."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from typing import Any


@dataclass(frozen=True)
class ForecastObservation:
    """One forecast made from information available at a historical timestamp."""

    observation_id: str
    market_id: str
    event_cluster_id: str
    evidence_state_id: str
    forecast_timestamp: str
    evidence_available_at: str
    evidence_published_at: str
    market_probability: float
    bot_probability: float
    resolved_yes: bool | None
    resolved_at: str | None
    evaluation_time_to_resolution_seconds: float | None
    category: str
    event_type: str
    expected_outcome: str
    match_score: int
    event_score: int
    relevance_confidence: float
    evidence_confidence: float
    evidence_recency_seconds: float
    source: str
    supporting_sources: tuple[str, ...]
    independent_confirmation_count: int
    independently_confirmed: bool
    liquidity: float | None
    volume: float | None
    is_new_evidence: bool
    event_title: str
    event_url: str
    match_reasons: tuple[str, ...]
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        forecast = self._time(self.forecast_timestamp)
        available = self._time(self.evidence_available_at)
        published = self._time(self.evidence_published_at)
        if available > forecast or published > forecast:
            raise ValueError("forecast observations cannot contain future evidence")
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in (
            self.market_probability,
            self.bot_probability,
            self.relevance_confidence,
            self.evidence_confidence,
        )):
            raise ValueError("forecast probabilities and confidence must be finite fractions")
        if self.resolved_yes is not None and self.resolved_at is None:
            raise ValueError("resolved observations require a resolution timestamp")
        if self.resolved_at is not None:
            resolved = self._time(self.resolved_at)
            if resolved <= forecast:
                raise ValueError("forecast timestamp must precede resolution")
        if (
            self.evaluation_time_to_resolution_seconds is not None
            and self.evaluation_time_to_resolution_seconds <= 0
        ):
            raise ValueError("time to resolution must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ForecastObservation":
        data = dict(value)
        for key in ("supporting_sources", "match_reasons"):
            data[key] = tuple(data.get(key, ()))
        return cls(**data)

    @staticmethod
    def _time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("forecast timestamps must be timezone-aware")
        return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class EvaluationMetrics:
    sample_count: int
    unique_market_count: int
    unique_event_cluster_count: int
    bot_brier_score: float | None
    market_brier_score: float | None
    brier_improvement: float | None
    bot_log_loss: float | None
    market_log_loss: float | None
    log_loss_improvement: float | None
    calibration_error: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BootstrapInterval:
    samples: int
    confidence_level: float
    lower: float | None
    upper: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationReport:
    overall: EvaluationMetrics
    breakdowns: dict[str, dict[str, EvaluationMetrics]]
    brier_improvement_interval: BootstrapInterval | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.to_dict(),
            "breakdowns": {
                name: {key: metrics.to_dict() for key, metrics in values.items()}
                for name, values in self.breakdowns.items()
            },
            "brier_improvement_interval": (
                self.brier_improvement_interval.to_dict()
                if self.brier_improvement_interval is not None else None
            ),
        }


@dataclass(frozen=True)
class ObservationSplit:
    train: tuple[ForecastObservation, ...]
    calibration: tuple[ForecastObservation, ...]
    test: tuple[ForecastObservation, ...]
    excluded_boundary_clusters: tuple[ForecastObservation, ...] = ()
