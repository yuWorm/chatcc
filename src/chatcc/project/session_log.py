from __future__ import annotations

import json
from pathlib import Path

from chatcc.project.models import SessionRecord


class SessionLog:
    """Append-only JSONL session log per project.

    Multiple lines may share the same session_id (updates).
    On read, the last entry per session_id wins.
    """

    def __init__(self, log_path: Path):
        self._path = log_path

    def append(self, record: SessionRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def _read_all_deduped(self) -> dict[str, SessionRecord]:
        """Read all lines, keeping last entry per session_id."""
        if not self._path.exists():
            return {}
        by_id: dict[str, SessionRecord] = {}
        for line in self._path.read_text(encoding="utf-8").strip().splitlines():
            try:
                record = SessionRecord.from_dict(json.loads(line))
                by_id[record.session_id] = record
            except (json.JSONDecodeError, KeyError):
                continue
        return by_id

    def get(self, session_id: str) -> SessionRecord | None:
        return self._read_all_deduped().get(session_id)

    def get_all(self) -> list[SessionRecord]:
        return list(self._read_all_deduped().values())

    def latest(self, n: int = 5) -> list[SessionRecord]:
        records = self.get_all()
        records.sort(key=lambda r: r.started_at)
        return records[-n:]

    def active(self) -> SessionRecord | None:
        for record in self._read_all_deduped().values():
            if record.status == "active":
                return record
        return None

    def count(self) -> int:
        return len(self._read_all_deduped())
