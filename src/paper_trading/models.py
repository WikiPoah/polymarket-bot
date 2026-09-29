# File-Version: 1.2.0
"""Persistent models for simulated strategy decisions."""

from dataclasses import asdict, dataclass
import hashlib
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.strategy.engine import StrategyDecision


@dataclass
class PaperDecision:
    """A paper decision whose position size and P/L are capital fractions."""

    id: str
    timestamp: str
    market: dict[str, Any]
    decision: str
    market_probability: float | None
    estimated_probability: float
    edge: float
    confidence: float
    position_size: float
    evidence_confidence: float
    evidence_count: int
    supporting_sources: list[str]
    event_title: str
    event_source: str
    event_url: str
    event_type: str = "OTHER"
    risk_status: str = "UNKNOWN"
    risk_reason: str = ""
    rationale: str = ""
    resolved_yes: bool | None = None
    result: str | None = None
    profit_loss: float = 0.0
    record_version: int = 3
    run_id: str = ""
    opportunity_id: str = ""
    resolved_at: str | None = None

    @classmethod
    def from_strategy_decision(
        cls,
        decision: StrategyDecision,
        run_id: str = "",
        decision_id: str | None = None,
        recorded_at: datetime | None = None,
    ) -> "PaperDecision":
        event = decision.opportunity.event.event
        paper_decision = cls(
            id=decision_id or str(uuid4()),
            timestamp=(recorded_at or datetime.now(timezone.utc)).isoformat(),
            market=dict(decision.opportunity.market),
            decision=decision.action.value,
            market_probability=decision.market_probability,
            estimated_probability=decision.estimated_probability,
            edge=decision.edge,
            confidence=decision.confidence,
            position_size=decision.position_size,
            evidence_confidence=event.evidence_confidence,
            evidence_count=event.evidence_count,
            supporting_sources=list(event.supporting_sources),
            event_title=event.title,
            event_source=event.source,
            event_url=event.source_url,
            event_type=event.event_type.value,
            risk_status=(
                "REJECTED"
                if any(reason.startswith("Risk rejected:") for reason in decision.reasons)
                else "ACCEPTED"
                if decision.action.value in {"BUY YES", "BUY NO"}
                else "IGNORED"
            ),
            risk_reason=next(
                (
                    reason.removeprefix("Risk rejected: ").strip()
                    for reason in decision.reasons
                    if reason.startswith("Risk rejected:")
                ),
                "",
            ),
            rationale=next(
                (
                    reason
                    for reason in reversed(decision.reasons)
                    if reason.startswith(("Accepted:", "Ignored:", "Risk rejected:"))
                ),
                "",
            ),
            run_id=run_id,
        )
        paper_decision.opportunity_id = paper_decision.build_opportunity_id()
        return paper_decision

    def build_opportunity_id(self) -> str:
        """Return a stable identifier for the same market/event/action tuple."""
        market_id = self.market.get("id") or self.market.get("conditionId")
        market_key = str(market_id or self.market.get("question", "")).strip().lower()
        event_key = str(self.event_url or self.event_title).strip().lower()
        value = "|".join((market_key, event_key, self.decision.strip().upper()))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperDecision":
        # Records written before event_type was introduced remain readable.
        values = dict(data)
        values.setdefault("event_type", "OTHER")
        values.setdefault("risk_status", "UNKNOWN")
        values.setdefault("risk_reason", "")
        values.setdefault("rationale", "")
        values.setdefault("record_version", 1)
        values.setdefault("run_id", "")
        values.setdefault("opportunity_id", "")
        values.setdefault("resolved_at", None)
        allowed = cls.__dataclass_fields__
        decision = cls(**{key: value for key, value in values.items() if key in allowed})
        if not decision.opportunity_id:
            decision.opportunity_id = decision.build_opportunity_id()
        return decision
