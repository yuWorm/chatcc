from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PendingApproval:
    id: int
    project: str
    tool_name: str
    input_summary: str
    future: asyncio.Future[str]
    choices: list[tuple[str, str]] | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_binary(self) -> bool:
        return self.choices is None


class ApprovalTable:
    def __init__(self):
        self._pending: dict[int, PendingApproval] = {}
        self._next_id = 1

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def _request(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
        *,
        choices: list[tuple[str, str]] | None = None,
    ) -> tuple[asyncio.Future[str], int]:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        approval_id = self._next_id
        entry = PendingApproval(
            id=approval_id,
            project=project,
            tool_name=tool_name,
            input_summary=input_summary,
            future=future,
            choices=choices,
        )
        self._pending[approval_id] = entry
        self._next_id += 1
        return future, approval_id

    def request_approval(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
    ) -> tuple[asyncio.Future[str], int]:
        """Register a pending approval and return ``(future, approval_id)``."""
        return self._request(project, tool_name, input_summary, choices=None)

    def request_choice(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
        choices: list[tuple[str, str]],
    ) -> tuple[asyncio.Future[str], int]:
        return self._request(
            project, tool_name, input_summary, choices=choices,
        )

    def get_pending(self, approval_id: int) -> PendingApproval | None:
        return self._pending.get(approval_id)

    def resolve(self, approval_id: int, value: str) -> bool:
        entry = self._pending.get(approval_id)
        if entry is None or entry.future.done():
            return False
        if entry.is_binary:
            if value not in ("approve", "deny"):
                return False
        else:
            allowed_values = {c[0] for c in (entry.choices or ())}
            if value not in allowed_values:
                return False
        del self._pending[approval_id]
        entry.future.set_result(value)
        return True

    def approve(self, approval_id: int) -> bool:
        return self.resolve(approval_id, "approve")

    def deny(self, approval_id: int) -> bool:
        return self.resolve(approval_id, "deny")

    def approve_oldest(self) -> bool:
        binary_ids = [
            eid for eid, e in self._pending.items() if e.is_binary
        ]
        if not binary_ids:
            return False
        oldest_id = min(binary_ids)
        return self.approve(oldest_id)

    def deny_oldest(self) -> bool:
        binary_ids = [
            eid for eid, e in self._pending.items() if e.is_binary
        ]
        if not binary_ids:
            return False
        oldest_id = min(binary_ids)
        return self.deny(oldest_id)

    def approve_all(self) -> int:
        count = 0
        for entry_id in list(self._pending.keys()):
            entry = self._pending.get(entry_id)
            if entry and entry.is_binary and self.approve(entry_id):
                count += 1
        return count

    def deny_all(self) -> int:
        count = 0
        for entry_id in list(self._pending.keys()):
            entry = self._pending.get(entry_id)
            if entry and entry.is_binary and self.deny(entry_id):
                count += 1
        return count

    def list_pending(self) -> list[PendingApproval]:
        return sorted(self._pending.values(), key=lambda x: x.id)
