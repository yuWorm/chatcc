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
class Project:
    name: str
    path: str
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False
    config: ProjectConfig = field(default_factory=ProjectConfig)
    current_task: TaskRecord | None = field(default=None, repr=False)
