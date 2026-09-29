# File-Version: 1.0.0
"""Shared errors for fail-closed durable JSON state."""

from pathlib import Path


class PersistenceCorruptionError(RuntimeError):
    """Existing persistent state is unsafe to read or overwrite."""

    def __init__(self, path: str | Path, detail: str) -> None:
        self.path = Path(path)
        self.detail = detail
        super().__init__(
            f"Persistent state is corrupted at {self.path}: {detail}; "
            "refusing to overwrite existing unreadable state."
        )
