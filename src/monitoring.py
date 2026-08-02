"""Persistent status records for automated evaluation runs."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunStatus:
    started_at: str
    completed_at: str
    success: bool
    markets_analyzed: int = 0
    decisions_generated: int = 0
    provider_status: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    run_id: str = ""
    provider_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    record_version: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "RunStatus":
        migrated = dict(values)
        migrated.setdefault("run_id", "")
        migrated.setdefault("provider_details", {})
        migrated.setdefault("record_version", 1)
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in migrated.items() if key in allowed})


class SystemStatusStore:
    """Store a bounded history of runner status records in JSON."""

    def __init__(
        self,
        path: str | Path = "data/system_status.json",
        maximum_runs: int = 100,
    ) -> None:
        self.path = Path(path)
        self.maximum_runs = maximum_runs

    def load(self) -> list[RunStatus]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, dict):
            payload = payload.get("records", [])
        if not isinstance(payload, list):
            return []
        statuses = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                statuses.append(RunStatus.from_dict(item))
            except (TypeError, ValueError):
                continue
        return statuses

    def record(self, status: RunStatus) -> None:
        statuses = [*self.load(), status][-self.maximum_runs:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(
                {"version": 2, "records": [item.to_dict() for item in statuses]},
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def latest(self) -> RunStatus | None:
        statuses = self.load()
        return statuses[-1] if statuses else None

    def last_successful(self) -> RunStatus | None:
        return next((item for item in reversed(self.load()) if item.success), None)
