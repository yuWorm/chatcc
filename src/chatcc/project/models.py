from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProjectConfig:
    permission_mode: str = "acceptEdits"
    setting_sources: list[str] = field(default_factory=lambda: ["project"])
    model: str | None = None


@dataclass
class Project:
    name: str
    path: str
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False
    config: ProjectConfig = field(default_factory=ProjectConfig)
