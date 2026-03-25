from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProjectConfig:
    permission_mode: str = "acceptEdits"
    setting_sources: list[str] = field(default_factory=lambda: ["project"])
    model: str | None = None


@dataclass
class TaskRecord:
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

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "project_name": self.project_name,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "task_ids": self.task_ids,
            "total_cost_usd": self.total_cost_usd,
            "status": self.status,
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
        )


@dataclass
class Project:
    name: str
    path: str
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False
    config: ProjectConfig = field(default_factory=ProjectConfig)
    current_task: TaskRecord | None = field(default=None, repr=False)
