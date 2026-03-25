from __future__ import annotations

import json
from pathlib import Path

from chatcc.project.models import TaskRecord


class TaskLog:
    """Append-only JSONL task log per project."""

    def __init__(self, log_path: Path):
        self._path = log_path

    def append(self, record: TaskRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def latest(self, n: int = 5) -> list[TaskRecord]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in lines[-n:]:
            try:
                records.append(TaskRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return records

    def last(self) -> TaskRecord | None:
        results = self.latest(1)
        return results[0] if results else None

    def count(self) -> int:
        if not self._path.exists():
            return 0
        return sum(1 for _ in open(self._path, encoding="utf-8"))
