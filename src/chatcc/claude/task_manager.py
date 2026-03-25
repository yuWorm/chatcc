from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from chatcc.claude.session import ProjectSession, TaskState

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
    ):
        self._project_manager = project_manager
        self._approval_table = approval_table
        self._on_notify = on_notify
        self._sessions: dict[str, ProjectSession] = {}
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_queues: dict[str, asyncio.Queue[Any]] = {}

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
        )
        self._sessions[project_name] = session
        return session

    async def submit_task(self, project_name: str, prompt: str) -> str:
        """Submit a dev task to a project. Returns status message.
        Same project serialized (rejects if RUNNING), cross-project parallel."""
        session = self.get_session(project_name)
        if not session:
            return f"错误: 项目 '{project_name}' 不存在"

        if session.task_state == TaskState.RUNNING:
            return f"项目 '{project_name}' 正在执行任务，请等待完成或使用 /stop"

        task = asyncio.create_task(self._run_task(session, prompt))
        self._running_tasks[project_name] = task
        return f"任务已提交到项目 '{project_name}'"

    async def _run_task(self, session: ProjectSession, prompt: str) -> None:
        """Execute a task on a session, handle completion/failure"""
        project_name = session.project.name
        try:
            result = await session.send_task(prompt)
            session.task_state = TaskState.COMPLETED
            cost = result.get("cost", 0.0) if result else 0.0
            await self._notify(project_name, f"✅ 任务完成 (${cost:.4f})")
        except asyncio.CancelledError:
            session.task_state = TaskState.CANCELLED
            await self._notify(project_name, "⏹️ 任务已取消")
            raise
        except Exception as exc:
            session.task_state = TaskState.FAILED
            await self._notify(project_name, f"❌ 任务失败: {exc}")
            raise
        finally:
            self._running_tasks.pop(project_name, None)

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
        for session in self._sessions.values():
            await session.disconnect()
        self._sessions.clear()
        self._running_tasks.clear()

    def _build_permission_handler(self):
        """Optional callback for dangerous tools when ApprovalTable is not used.

        Risk assessment and ApprovalTable are wired on ProjectSession directly;
        this remains for custom on_permission overrides if added later.
        """
        return None
