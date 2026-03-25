from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


class LongTermMemory:
    def __init__(self, memory_dir: Path | None = None):
        self._dir = memory_dir or (Path.home() / ".chatcc" / "memory")
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def _core_file(self) -> Path:
        return self._dir / "MEMORY.md"

    def read_core(self) -> str:
        if not self._core_file.exists():
            return ""
        return self._core_file.read_text(encoding="utf-8")

    def write_core(self, content: str) -> None:
        self._core_file.write_text(content, encoding="utf-8")

    def append_daily_note(self, note: str) -> None:
        today = datetime.now()
        month_dir = self._dir / today.strftime("%Y%m")
        month_dir.mkdir(parents=True, exist_ok=True)

        daily_file = month_dir / f"{today.strftime('%Y%m%d')}.md"
        timestamp = today.strftime("%H:%M")

        with open(daily_file, "a", encoding="utf-8") as f:
            f.write(f"- [{timestamp}] {note}\n")

    def get_recent_daily_notes(self, days: int = 3) -> list[str]:
        notes = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            month_dir = self._dir / date.strftime("%Y%m")
            daily_file = month_dir / f"{date.strftime('%Y%m%d')}.md"
            if daily_file.exists():
                notes.append(daily_file.read_text(encoding="utf-8"))
        return notes

    def get_context(self, recent_days: int = 3) -> str:
        parts = []
        core = self.read_core()
        if core:
            parts.append(f"## 长期记忆\n{core}")

        daily_notes = self.get_recent_daily_notes(days=recent_days)
        if daily_notes:
            parts.append("## 近期笔记")
            for note in daily_notes:
                parts.append(note)

        return "\n\n".join(parts)
