"""Orchestration for one-shot and continuous paper-trading evaluation."""

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from typing import Callable, Protocol
from uuid import uuid4
from datetime import timedelta

from src.paper_trading.history import PaperTradingRecorder

from src.monitoring import RunStatus, SystemStatusStore
from src.strategy.engine import StrategyDecision


class MarketSource(Protocol):
    def get_active_markets(self) -> list[dict]: ...


class EvaluationPipeline(Protocol):
    provider_status: dict[str, str]
    provider_errors: list[str]
    provider_details: dict[str, dict]

    def reset_provider_status(self) -> None: ...
    def run(self, markets: list[dict]) -> list[StrategyDecision]: ...


@dataclass(frozen=True)
class EvaluationResult:
    status: RunStatus
    decisions: tuple[StrategyDecision, ...]


class EvaluationRunner:
    """Fetch markets and invoke the existing paper-trading pipeline on a schedule."""

    def __init__(
        self,
        market_source: MarketSource,
        pipeline: EvaluationPipeline,
        status_store: SystemStatusStore | None = None,
        market_filter: Callable[[list[dict]], list[dict]] | None = None,
        clock: Callable[[], datetime] | None = None,
        recorder: PaperTradingRecorder | None = None,
        duplicate_window_seconds: float = 3600.0,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.market_source = market_source
        self.pipeline = pipeline
        self.status_store = status_store or SystemStatusStore()
        self.market_filter = market_filter or (lambda markets: markets)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.recorder = recorder
        self.duplicate_window_seconds = duplicate_window_seconds
        self.run_id_factory = run_id_factory or (lambda: str(uuid4()))
        if duplicate_window_seconds < 0:
            raise ValueError("duplicate_window_seconds cannot be negative")

    def run_once(self) -> EvaluationResult:
        run_id = self.run_id_factory()
        started_at = self.clock().isoformat()
        markets_analyzed = 0
        decisions: list[StrategyDecision] = []
        errors: list[str] = []
        success = False
        self.pipeline.reset_provider_status()
        if self.recorder is not None:
            self.recorder.begin_run(
                run_id,
                timedelta(seconds=self.duplicate_window_seconds),
            )

        try:
            markets = self.market_filter(self.market_source.get_active_markets())
            markets_analyzed = len(markets)
            decisions = self.pipeline.run(markets) if markets else []
            errors.extend(self.pipeline.provider_errors)
            success = True
        except Exception as error:  # Runner boundary records failures for the next cycle.
            errors.append(f"{type(error).__name__}: {error}")

        status = RunStatus(
            started_at=started_at,
            completed_at=self.clock().isoformat(),
            success=success,
            markets_analyzed=markets_analyzed,
            decisions_generated=len(decisions),
            provider_status=self.pipeline.provider_status,
            errors=errors,
            run_id=run_id,
            provider_details=self.pipeline.provider_details,
        )
        self.status_store.record(status)
        return EvaluationResult(status=status, decisions=tuple(decisions))

    def run_forever(
        self,
        interval_seconds: float,
        stop_event: Event | None = None,
        on_result: Callable[[EvaluationResult], None] | None = None,
    ) -> None:
        EvaluationScheduler(interval_seconds).run(self, stop_event, on_result)


class EvaluationScheduler:
    """Interruptible fixed-delay scheduler for evaluation cycles."""

    def __init__(self, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds

    def run(
        self,
        runner: EvaluationRunner,
        stop_event: Event | None = None,
        on_result: Callable[[EvaluationResult], None] | None = None,
    ) -> None:
        stop_event = stop_event or Event()
        while not stop_event.is_set():
            result = runner.run_once()
            if on_result is not None:
                on_result(result)
            stop_event.wait(self.interval_seconds)
