from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from chatcc.config import ClaudeDefaultsConfig
from chatcc.project.models import Project, ProjectConfig


class ProjectManager:
    def __init__(
        self,
        data_dir: Path | None = None,
        workspace_root: Path | str | None = None,
        claude_defaults: ClaudeDefaultsConfig | None = None,
    ):
        self._data_dir = data_dir or (Path.home() / ".chatcc" / "projects")
        self._workspace_root = Path(workspace_root).expanduser().resolve() if workspace_root else Path.home() / "projects"
        self._claude_defaults = claude_defaults
        self._projects: dict[str, Project] = {}
        self._load_all()

    def _resolve_project_path(self, path: str) -> str:
        """Resolve a project path against workspace_root if it's relative.

        Handles ~ expansion in both the path and workspace_root.
        """
        p = Path(path).expanduser()
        if p.is_absolute():
            return str(p.resolve())
        return str((self._workspace_root / p).resolve())

    @property
    def default_project(self) -> Project | None:
        for p in self._projects.values():
            if p.is_default:
                return p
        return None

    @property
    def active_count(self) -> int:
        return len(self._projects)

    def create_project(self, name: str, path: str) -> Project:
        if name in self._projects:
            raise ValueError(f"Project '{name}' already exists")

        is_default = len(self._projects) == 0
        resolved_path = self._resolve_project_path(path)

        config = ProjectConfig()
        if self._claude_defaults:
            config.permission_mode = self._claude_defaults.permission_mode
            config.setting_sources = list(self._claude_defaults.setting_sources)
            config.model = self._claude_defaults.model

        project = Project(
            name=name, path=resolved_path,
            is_default=is_default, config=config,
        )
        self._projects[name] = project
        self._save_project(project)
        return project

    def list_projects(self) -> list[Project]:
        return list(self._projects.values())

    def get_project(self, name: str) -> Project | None:
        return self._projects.get(name)

    def project_dir(self, name: str) -> Path | None:
        if name not in self._projects:
            return None
        return self._data_dir / name

    def switch_default(self, name: str) -> Project:
        if name not in self._projects:
            raise ValueError(f"Project '{name}' not found")

        for p in self._projects.values():
            if p.is_default:
                p.is_default = False
                self._save_project(p)

        project = self._projects[name]
        project.is_default = True
        self._save_project(project)
        return project

    def update_config(
        self,
        name: str,
        *,
        model: str | None = ...,
        permission_mode: str | None = ...,
        setting_sources: list[str] | None = ...,
    ) -> Project:
        project = self._projects.get(name)
        if not project:
            raise ValueError(f"Project '{name}' not found")

        if model is not ...:
            project.config.model = model
        if permission_mode is not ...:
            project.config.permission_mode = permission_mode or "acceptEdits"
        if setting_sources is not ...:
            project.config.setting_sources = setting_sources or ["project"]

        self._save_project(project)
        return project

    def delete_project(self, name: str) -> None:
        project = self._projects.pop(name, None)
        if not project:
            raise ValueError(f"Project '{name}' not found")

        proj_dir = self._data_dir / name
        if proj_dir.exists():
            import shutil
            shutil.rmtree(proj_dir)

        if project.is_default and self._projects:
            first = next(iter(self._projects.values()))
            first.is_default = True
            self._save_project(first)

    def _save_project(self, project: Project) -> None:
        proj_dir = self._data_dir / project.name
        proj_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "name": project.name,
            "path": project.path,
            "created_at": project.created_at.isoformat(),
            "is_default": project.is_default,
            "claude_options": {
                "permission_mode": project.config.permission_mode,
                "setting_sources": project.config.setting_sources,
                "model": project.config.model,
            },
        }
        with open(proj_dir / "project.yaml", "w") as f:
            yaml.dump(data, f, allow_unicode=True)

    def _load_all(self) -> None:
        if not self._data_dir.exists():
            return

        for proj_dir in self._data_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            config_file = proj_dir / "project.yaml"
            if not config_file.exists():
                continue
            try:
                with open(config_file) as f:
                    data = yaml.safe_load(f) or {}
                claude_opts = data.get("claude_options", {})
                project = Project(
                    name=data["name"],
                    path=self._resolve_project_path(data["path"]),
                    created_at=datetime.fromisoformat(
                        data.get("created_at", datetime.now().isoformat())
                    ),
                    is_default=data.get("is_default", False),
                    config=ProjectConfig(
                        permission_mode=claude_opts.get("permission_mode", "acceptEdits"),
                        setting_sources=claude_opts.get("setting_sources", ["project"]),
                        model=claude_opts.get("model"),
                    ),
                )
                self._projects[project.name] = project
            except Exception:
                continue
