"""Dashboard presentation data built from existing paper-trading services."""

from typing import Any

from src.paper_trading.analytics import PerformanceAnalytics
from src.paper_trading.history import PaperTradingRecorder
from src.paper_trading.models import PaperDecision
from src.monitoring import RunStatus, SystemStatusStore


class DashboardDataBuilder:
    """Adapt persisted decisions into JSON-ready dashboard sections."""

    def __init__(
        self,
        recorder: PaperTradingRecorder | None = None,
        status_store: SystemStatusStore | None = None,
    ) -> None:
        self.recorder = recorder or PaperTradingRecorder()
        self.status_store = status_store or SystemStatusStore()
        self.analytics = PerformanceAnalytics()

    def build(self) -> dict[str, Any]:
        decisions = self.recorder.load()
        report = self.analytics.analyze(decisions)
        statuses = self.status_store.load()
        latest = statuses[-1] if statuses else None
        last_successful = next(
            (item for item in reversed(statuses) if item.success),
            None,
        )
        return {
            "current_opportunities": [
                self._decision_view(decision)
                for decision in decisions
                if decision.result is None
            ],
            "performance": self._summary_view(report.summary),
            "history": [self._decision_view(decision) for decision in decisions],
            "breakdowns": {
                "event_type": {
                    key: self._summary_view(value)
                    for key, value in report.by_event_type.items()
                },
                "confidence": {
                    key: self._summary_view(value)
                    for key, value in report.by_confidence.items()
                },
                "evidence_strength": {
                    key: self._summary_view(value)
                    for key, value in report.by_evidence_strength.items()
                },
            },
            "calibration": [
                {
                    "lower_bound": bucket.lower_bound,
                    "upper_bound": bucket.upper_bound,
                    "count": bucket.count,
                    "average_predicted": bucket.average_predicted,
                    "actual_rate": bucket.actual_rate,
                }
                for bucket in report.calibration
            ],
            "brier_score": report.brier_score,
            "system": {
                "health": self._health(latest),
                "latest_run": self._run_view(latest),
                "last_successful_run": (
                    last_successful.completed_at if last_successful else None
                ),
                "data_freshness": (
                    last_successful.completed_at if last_successful else None
                ),
                "recent_runs": [self._run_view(item) for item in statuses[-10:][::-1]],
                "provider_freshness": latest.provider_details if latest else {},
            },
            "recent_activity": [
                self._decision_view(decision) for decision in decisions[-10:][::-1]
            ],
        }

    @staticmethod
    def _health(status: RunStatus | None) -> str:
        if status is None:
            return "UNKNOWN"
        if not status.success:
            return "ERROR"
        return "DEGRADED" if status.errors else "HEALTHY"

    @staticmethod
    def _run_view(status: RunStatus | None) -> dict[str, Any] | None:
        return status.to_dict() if status else None

    @staticmethod
    def _summary_view(summary) -> dict[str, Any]:
        return {
            "total_decisions": summary.total_decisions,
            "executed_trades": summary.executed_trades,
            "wins": summary.wins,
            "losses": summary.losses,
            "win_rate": summary.win_rate,
            "profit_loss": summary.profit_loss,
            "average_edge": summary.average_edge,
            "average_confidence": summary.average_confidence,
        }

    @staticmethod
    def _decision_view(decision: PaperDecision) -> dict[str, Any]:
        return {
            "id": decision.id,
            "run_id": decision.run_id,
            "opportunity_id": decision.opportunity_id,
            "timestamp": decision.timestamp,
            "market_question": decision.market.get("question", ""),
            "decision": decision.decision,
            "estimated_probability": decision.estimated_probability,
            "market_probability": decision.market_probability,
            "edge": decision.edge,
            "confidence": decision.confidence,
            "position_size": decision.position_size,
            "supporting_sources": decision.supporting_sources,
            "evidence_count": decision.evidence_count,
            "risk_status": decision.risk_status,
            "risk_reason": decision.risk_reason,
            "event_type": decision.event_type,
            "event_title": decision.event_title,
            "result": decision.result,
            "profit_loss": decision.profit_loss,
        }
