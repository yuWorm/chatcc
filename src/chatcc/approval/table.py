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
    future: asyncio.Future
    created_at: datetime = field(default_factory=datetime.now)


class ApprovalTable:
    def __init__(self):
        self._pending: dict[int, PendingApproval] = {}
        self._next_id = 1

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def request_approval(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
    ) -> tuple[asyncio.Future[bool], int]:
        """Register a pending approval and return ``(future, approval_id)``."""
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        approval_id = self._next_id
        entry = PendingApproval(
            id=approval_id,
            project=project,
            tool_name=tool_name,
            input_summary=input_summary,
            future=future,
        )
        self._pending[approval_id] = entry
        self._next_id += 1
        return future, approval_id

    def approve(self, approval_id: int) -> bool:
        entry = self._pending.pop(approval_id, None)
        if entry and not entry.future.done():
            entry.future.set_result(True)
            return True
        return False

    def deny(self, approval_id: int) -> bool:
        entry = self._pending.pop(approval_id, None)
        if entry and not entry.future.done():
            entry.future.set_result(False)
            return True
        return False

    def approve_oldest(self) -> bool:
        if not self._pending:
            return False
        oldest_id = min(self._pending.keys())
        return self.approve(oldest_id)

    def deny_oldest(self) -> bool:
        if not self._pending:
            return False
        oldest_id = min(self._pending.keys())
        return self.deny(oldest_id)

    def approve_all(self) -> int:
        count = 0
        for entry_id in list(self._pending.keys()):
            if self.approve(entry_id):
                count += 1
        return count

    def deny_all(self) -> int:
        count = 0
        for entry_id in list(self._pending.keys()):
            if self.deny(entry_id):
                count += 1
        return count

    def list_pending(self) -> list[PendingApproval]:
        return sorted(self._pending.values(), key=lambda x: x.id)
