"""Persistent models for simulated strategy decisions."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.strategy.engine import StrategyDecision


@dataclass
class PaperDecision:
    """A strategy decision captured without placing an order."""

    id: str
    timestamp: str
    market: dict[str, Any]
    decision: str
    market_probability: float
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
    resolved_yes: bool | None = None
    result: str | None = None
    profit_loss: float = 0.0

    @classmethod
    def from_strategy_decision(cls, decision: StrategyDecision) -> "PaperDecision":
        event = decision.opportunity.event.event
        return cls(
            id=str(uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
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
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperDecision":
        return cls(**data)
