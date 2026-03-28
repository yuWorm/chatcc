from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class RunningService:
    name: str
    project: str
    pid: int
    command: str
    started_at: datetime = field(default_factory=datetime.now)
    log_file: Path = field(default_factory=Path)


class ServiceManager:
    def __init__(self, services_dir: Path | None = None):
        self._services_dir = services_dir or (Path.home() / "services")
        self._services: dict[str, dict[str, RunningService]] = {}

    async def start(
        self, project: str, name: str, command: str, cwd: str
    ) -> RunningService:
        """Start a background service process in the project directory.

        Args:
            project: Project name
            name: Service name (e.g. "dev-server", "watcher")
            command: Shell command to run
            cwd: Working directory (project path)

        Returns:
            RunningService with PID and log file info

        Raises:
            ValueError: If service with same name already running for project
        """
        if project in self._services and name in self._services[project]:
            existing = self._services[project][name]
            if self._is_process_running(existing.pid):
                raise ValueError(
                    f"Service '{name}' already running for project '{project}' (PID {existing.pid})"
                )
            self._remove_service(project, name)

        log_dir = self._services_dir / project
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{name}.log"

        log_fh = open(log_file, "a", encoding="utf-8", errors="replace")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=log_fh,
                stderr=log_fh,
                start_new_session=True,
            )
        finally:
            log_fh.close()

        service = RunningService(
            name=name,
            project=project,
            pid=proc.pid,
            command=command,
            log_file=log_file,
        )

        if project not in self._services:
            self._services[project] = {}
        self._services[project][name] = service

        return service

    async def stop(self, project: str, name: str) -> bool:
        """Stop a service. SIGTERM first, then SIGKILL after 3s.
        Returns True if service was stopped."""
        service = self._get_service(project, name)
        if not service:
            return False

        if not self._is_process_running(service.pid):
            self._remove_service(project, name)
            return True

        try:
            os.killpg(os.getpgid(service.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            self._remove_service(project, name)
            return True

        for _ in range(30):
            await asyncio.sleep(0.1)
            if not self._is_process_running(service.pid):
                self._remove_service(project, name)
                return True

        try:
            os.killpg(os.getpgid(service.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

        self._remove_service(project, name)
        return True

    def status(self, project: str | None = None) -> list[RunningService]:
        """List running services, optionally filtered by project."""
        result: list[RunningService] = []
        to_remove: list[tuple[str, str]] = []
        projects = [project] if project is not None else list(self._services.keys())
        for proj in projects:
            if proj not in self._services:
                continue
            for name, svc in list(self._services[proj].items()):
                if self._is_process_running(svc.pid):
                    result.append(svc)
                else:
                    to_remove.append((proj, name))
        for proj, name in to_remove:
            self._remove_service(proj, name)
        return result

    async def logs(self, project: str, name: str, lines: int = 50) -> str:
        """Read last N lines from service log file."""
        service = self._get_service(project, name)
        if not service:
            return f"服务 '{name}' 未找到"

        if not service.log_file.exists():
            return "(无日志)"

        all_lines = service.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return "\n".join(recent)

    async def stop_all(self, project: str | None = None) -> int:
        """Stop all services, optionally for a specific project."""
        count = 0
        projects = [project] if project is not None else list(self._services.keys())
        for proj in list(projects):
            if proj in self._services:
                for name in list(self._services[proj].keys()):
                    if await self.stop(proj, name):
                        count += 1
        return count

    def _get_service(self, project: str, name: str) -> RunningService | None:
        return self._services.get(project, {}).get(name)

    def _remove_service(self, project: str, name: str) -> None:
        if project in self._services:
            self._services[project].pop(name, None)
            if not self._services[project]:
                del self._services[project]

    @staticmethod
    def _is_process_running(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except ProcessLookupError:
            return False
