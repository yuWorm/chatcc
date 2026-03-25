from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class ConversationHistory:
    def __init__(self, storage_dir: Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._storage_dir / "history.jsonl"
        self._messages: list[dict[str, Any]] = []
        self._load()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def add_message(self, role: str, content: str) -> None:
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        self._messages.append(entry)
        self._append_to_file(entry)

    def get_messages(self, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is None:
            return list(self._messages)
        return list(self._messages[-limit:])

    def truncate(self, keep_recent: int = 10) -> list[dict[str, Any]]:
        removed = (
            self._messages[:-keep_recent]
            if keep_recent < len(self._messages)
            else []
        )
        self._messages = self._messages[-keep_recent:]
        self._rewrite_file()
        return removed

    def flush(self) -> None:
        self._rewrite_file()

    def _append_to_file(self, entry: dict) -> None:
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rewrite_file(self) -> None:
        with open(self._file, "w", encoding="utf-8") as f:
            for entry in self._messages:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load(self) -> None:
        if not self._file.exists():
            return
        with open(self._file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self._messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
