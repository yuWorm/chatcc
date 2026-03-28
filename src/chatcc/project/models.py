from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class ProjectConfig:
    permission_mode: str = "acceptEdits"
    setting_sources: list[str] = field(default_factory=lambda: ["project"])
    model: str | None = None


@dataclass
class SessionPolicy:
    """Controls per-project session lifecycle behaviour."""

    max_tasks_per_session: int = 10
    max_cost_per_session: float = 2.0
    idle_disconnect_seconds: int = 300


@dataclass
class TaskRecord:
    """Status values: queued, running, completed, failed, cancelled, interrupted."""

    prompt: str
    status: str = "running"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    submitted_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    cost_usd: float = 0.0
    session_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "status": self.status,
            "submitted_at": self.submitted_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "cost_usd": self.cost_usd,
            "session_id": self.session_id,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskRecord:
        return cls(
            id=data["id"],
            prompt=data["prompt"],
            status=data.get("status", "unknown"),
            submitted_at=datetime.fromisoformat(data["submitted_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            cost_usd=data.get("cost_usd", 0.0),
            session_id=data.get("session_id"),
            error=data.get("error"),
        )


@dataclass
class SessionRecord:
    """A Claude Code session that may span multiple tasks."""

    session_id: str
    project_name: str
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: datetime | None = None
    task_ids: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0
    status: str = "active"
    summary: str | None = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project_name": self.project_name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "task_ids": self.task_ids,
            "total_cost_usd": self.total_cost_usd,
            "status": self.status,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionRecord:
        return cls(
            session_id=data["session_id"],
            project_name=data["project_name"],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None,
            task_ids=data.get("task_ids", []),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            status=data.get("status", "active"),
            summary=data.get("summary"),
        )


@dataclass
class QueuedTask:
    """A task waiting in the per-project queue."""

    prompt: str
    record: TaskRecord
    priority: int = 0  # 0=normal, -1=immediate (lower value = higher priority)

    def __lt__(self, other: QueuedTask) -> bool:
        return (self.priority, self.record.submitted_at) < (
            other.priority,
            other.record.submitted_at,
        )


@dataclass
class SubmitResult:
    """Structured result from TaskManager.submit_task."""

    status: Literal["submitted", "queued", "conflict", "error"]
    message: str
    task_id: str | None = None
    queue_position: int = 0


@dataclass
class Project:
    name: str
    path: str
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False
    config: ProjectConfig = field(default_factory=ProjectConfig)
    current_task: TaskRecord | None = field(default=None, repr=False)
