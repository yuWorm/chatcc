from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from chatcc.claude.session import ProjectSession, TaskState
from chatcc.project.models import SessionRecord, TaskRecord
from chatcc.project.session_log import SessionLog
from chatcc.project.task_log import TaskLog

if TYPE_CHECKING:
    from chatcc.approval.table import ApprovalTable
    from chatcc.project.manager import ProjectManager


class TaskManager:
    """管理所有项目的 ProjectSession 生命周期"""

    def __init__(
        self,
        project_manager: ProjectManager,
        approval_table: ApprovalTable | None = None,
        on_notify: Callable[[str, str], Awaitable[None]] | None = None,
        dangerous_patterns: dict[str, list[str]] | None = None,
    ):
        self._project_manager = project_manager
        self._approval_table = approval_table
        self._on_notify = on_notify
        self._dangerous_patterns = dangerous_patterns
        self._sessions: dict[str, ProjectSession] = {}
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_logs: dict[str, TaskLog] = {}
        self._session_logs: dict[str, SessionLog] = {}

    def get_session(self, project_name: str) -> ProjectSession | None:
        """Get existing session for a project, or create one if the project exists"""
        if project_name in self._sessions:
            return self._sessions[project_name]
        project = self._project_manager.get_project(project_name)
        if not project:
            return None
        session = ProjectSession(
            project=project,
            on_notification=self._on_notify,
            on_permission=self._build_permission_handler(),
            approval_table=self._approval_table,
            dangerous_patterns=self._dangerous_patterns,
        )
        self._sessions[project_name] = session
        return session

    def get_task_log(self, project_name: str) -> TaskLog | None:
        if project_name in self._task_logs:
            return self._task_logs[project_name]
        data_dir = self._project_manager.project_dir(project_name)
        if not data_dir:
            return None
        log = TaskLog(data_dir / "tasks.jsonl")
        self._task_logs[project_name] = log
        return log

    def get_session_log(self, project_name: str) -> SessionLog | None:
        if project_name in self._session_logs:
            return self._session_logs[project_name]
        data_dir = self._project_manager.project_dir(project_name)
        if not data_dir:
            return None
        log = SessionLog(data_dir / "sessions.jsonl")
        self._session_logs[project_name] = log
        return log

    def _update_session(self, project_name: str, record: TaskRecord) -> None:
        """Create or update a SessionRecord after a task completes."""
        if not record.session_id:
            return
        session_log = self.get_session_log(project_name)
        if not session_log:
            return
        existing = session_log.get(record.session_id)
        if existing:
            if record.id not in existing.task_ids:
                existing.task_ids.append(record.id)
            existing.total_cost_usd += record.cost_usd
            session_log.append(existing)
        else:
            sr = SessionRecord(
                session_id=record.session_id,
                project_name=project_name,
                task_ids=[record.id],
                total_cost_usd=record.cost_usd,
            )
            session_log.append(sr)

    def close_session(self, project_name: str) -> bool:
        """Mark the active session for a project as closed. Returns True if closed."""
        session_log = self.get_session_log(project_name)
        if not session_log:
            return False
        active = session_log.active()
        if not active:
            return False
        active.status = "closed"
        active.ended_at = datetime.now()
        session_log.append(active)
        return True

    async def submit_task(self, project_name: str, prompt: str) -> str:
        """Submit a dev task to a project. Returns status message.
        Same project serialized (rejects if RUNNING), cross-project parallel.

        Phase 1 (awaited): connect + send query — failures return error directly.
        Phase 2 (background): consume response stream — fires as asyncio.Task.
        """
        session = self.get_session(project_name)
        if not session:
            return f"错误: 项目 '{project_name}' 不存在"

        if session.task_state == TaskState.RUNNING:
            return f"项目 '{project_name}' 正在执行任务，请等待完成或使用 /stop"

        record = TaskRecord(prompt=prompt, session_id=session.active_session_id)
        session.project.current_task = record

        # Phase 1: connect + send query (awaited, errors return immediately)
        try:
            client = await session.ensure_connected()
            session.task_state = TaskState.RUNNING
            await client.query(prompt)
        except Exception as exc:
            session.task_state = TaskState.FAILED
            record.status = "failed"
            record.error = str(exc)[:500]
            record.completed_at = datetime.now()
            session.project.current_task = None
            task_log = self.get_task_log(project_name)
            if task_log:
                task_log.append(record)
            await session.disconnect()
            return f"错误: 任务启动失败 — {exc}"

        # Phase 2: consume response stream (background)
        task = asyncio.create_task(
            self._consume_task(session, record)
        )
        self._running_tasks[project_name] = task
        return f"任务已提交到项目 '{project_name}' (#{record.id})"

    async def _consume_task(
        self, session: ProjectSession, record: TaskRecord
    ) -> None:
        """Phase 2: consume the response stream after query was sent."""
        project_name = session.project.name
        try:
            result = await session.consume_response()
            session.task_state = TaskState.COMPLETED
            cost = result.get("cost", 0.0) if result else 0.0
            record.status = "completed"
            record.cost_usd = cost
            record.session_id = result.get("session_id") if result else record.session_id
            await self._notify(project_name, f"✅ 任务完成 (${cost:.4f})")
        except asyncio.CancelledError:
            session.task_state = TaskState.CANCELLED
            record.status = "cancelled"
            await self._notify(project_name, "⏹️ 任务已取消")
            raise
        except Exception as exc:
            session.task_state = TaskState.FAILED
            record.status = "failed"
            record.error = str(exc)[:500]
            await self._notify(project_name, f"❌ 任务失败: {exc}")
            raise
        finally:
            record.completed_at = datetime.now()
            self._running_tasks.pop(project_name, None)
            task_log = self.get_task_log(project_name)
            if task_log:
                task_log.append(record)
            self._update_session(project_name, record)
            session.project.current_task = None
            await session.disconnect()

    async def _notify(self, project_name: str, message: str) -> None:
        if self._on_notify:
            try:
                await self._on_notify(project_name, message)
            except Exception:
                pass

    async def interrupt_task(self, project_name: str) -> str:
        """Interrupt the running task for a project"""
        session = self._sessions.get(project_name)
        if not session:
            return f"项目 '{project_name}' 无活跃会话"
        if session.task_state != TaskState.RUNNING:
            return f"项目 '{project_name}' 当前无运行中的任务"

        await session.interrupt()
        task = self._running_tasks.get(project_name)
        if task:
            task.cancel()
        return f"已中断项目 '{project_name}' 的任务"

    def get_task_status(self, project_name: str) -> str:
        """Get task status for a project"""
        session = self._sessions.get(project_name)
        if not session:
            return "无活跃会话"
        return session.task_state.value

    def get_all_status(self) -> dict[str, str]:
        """Get status of all active sessions"""
        return {name: s.task_state.value for name, s in self._sessions.items()}

    async def shutdown(self) -> None:
        """Gracefully shutdown all sessions"""
        tasks = list(self._running_tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for name in list(self._sessions):
            self.close_session(name)
        for session in self._sessions.values():
            try:
                await session.disconnect()
            except RuntimeError:
                pass
        self._sessions.clear()
        self._running_tasks.clear()

    def _build_permission_handler(self):
        """Optional callback for dangerous tools when ApprovalTable is not used.

        Risk assessment and ApprovalTable are wired on ProjectSession directly;
        this remains for custom on_permission overrides if added later.
        """
        return None
