from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from chatcc.channel.compose import (
    compose_retry_failed,
    compose_retry_success,
    compose_session_rotated,
    compose_task_completed,
    compose_task_failed,
    compose_task_interrupted,
)
from chatcc.channel.message import RichMessage
from chatcc.claude.session import ProjectSession, TaskState
from chatcc.project.models import (
    QueuedTask,
    SessionRecord,
    SubmitResult,
    TaskRecord,
)
from chatcc.project.session_log import SessionLog
from chatcc.project.task_log import TaskLog

if TYPE_CHECKING:
    from chatcc.approval.table import ApprovalTable
    from chatcc.config import SessionPolicyConfig
    from chatcc.project.manager import ProjectManager

_CONTEXT_TOO_LONG_MARKERS = ("context_length", "too long", "max_tokens", "context window")
_PROCESS_ERROR_MARKERS = ("terminated process", "Cannot write", "process failed", "exit code")


class TaskManager:
    """Manages per-project task queues, workers, and ProjectSession lifecycles."""

    def __init__(
        self,
        project_manager: ProjectManager,
        approval_table: ApprovalTable | None = None,
        on_notify: Callable[[str, str | RichMessage], Awaitable[None]] | None = None,
        dangerous_patterns: dict[str, list[str]] | None = None,
        session_policy: SessionPolicyConfig | None = None,
    ):
        self._project_manager = project_manager
        self._approval_table = approval_table
        self._on_notify: Callable[[str, str | RichMessage], Awaitable[None]] | None = on_notify
        self._dangerous_patterns = dangerous_patterns

        if session_policy is None:
            from chatcc.config import SessionPolicyConfig
            session_policy = SessionPolicyConfig()
        self._policy = session_policy

        self._sessions: dict[str, ProjectSession] = {}
        self._queues: dict[str, asyncio.PriorityQueue[tuple[int, float, QueuedTask]]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._current_tasks: dict[str, QueuedTask] = {}
        self._task_logs: dict[str, TaskLog] = {}
        self._session_logs: dict[str, SessionLog] = {}

    # ── Session / log accessors ────────────────────────────────────

    def get_session(self, project_name: str) -> ProjectSession | None:
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
        self._restore_session_id(project_name, session)
        self._sessions[project_name] = session
        return session

    def _restore_session_id(
        self, project_name: str, session: ProjectSession
    ) -> None:
        """Try to restore active_session_id from the session log.

        Falls back to the SDK ``list_sessions`` when our own log has no
        active record (e.g. after a clean shutdown that closed all sessions).
        This allows the ``resume`` parameter to reconnect to the previous
        Claude Code session after a process restart.
        """
        session_log = self.get_session_log(project_name)
        if session_log:
            active = session_log.active()
            if active:
                session.active_session_id = active.session_id
                logger.info(
                    "Restored session {} for '{}' (source=session_log)",
                    active.session_id[:12],
                    project_name,
                )
                return

        try:
            from claude_agent_sdk import list_sessions

            sdk_sessions = list_sessions(
                directory=session.project.path, limit=1,
            )
            if sdk_sessions:
                sid = sdk_sessions[0].session_id
                session.active_session_id = sid
                logger.info(
                    "Restored session {} for '{}' (source=sdk)",
                    sid[:12],
                    project_name,
                )
                return
        except Exception as exc:
            logger.debug(
                "SDK list_sessions failed for '{}': {}",
                project_name,
                exc,
            )

        logger.debug("No session to restore for '{}'", project_name)

    async def restore_all_sessions(self) -> int:
        """Proactively restore session IDs for all known projects.

        Returns the number of sessions successfully restored.
        """
        projects = self._project_manager.list_projects()
        logger.info(
            "Restoring sessions on startup ({} project(s))...",
            len(projects),
        )
        restored = 0
        for project in projects:
            session = self.get_session(project.name)
            if not session:
                logger.warning(
                    "Skip restore for '{}': failed to create session",
                    project.name,
                )
                continue
            if session.active_session_id:
                restored += 1
            else:
                logger.debug(
                    "No active session to restore for '{}'",
                    project.name,
                )
        logger.info(
            "Session restore complete: {}/{} project(s) resumed",
            restored,
            len(projects),
        )
        return restored

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

    # ── Queue infrastructure ───────────────────────────────────────

    def _ensure_queue(self, project_name: str) -> asyncio.PriorityQueue[tuple[int, float, QueuedTask]]:
        if project_name not in self._queues:
            self._queues[project_name] = asyncio.PriorityQueue()
        return self._queues[project_name]

    def _ensure_worker(self, project_name: str) -> None:
        worker = self._workers.get(project_name)
        if worker and not worker.done():
            return
        self._workers[project_name] = asyncio.create_task(
            self._worker_loop(project_name),
            name=f"worker-{project_name}",
        )

    # ── Submit / enqueue / interrupt ───────────────────────────────

    async def submit_task(self, project_name: str, prompt: str) -> SubmitResult:
        """Submit a task. Returns *conflict* when the project is already busy
        so the caller can ask the user what to do."""
        session = self.get_session(project_name)
        if not session:
            return SubmitResult(status="error", message=f"错误: 项目 '{project_name}' 不存在")

        is_busy = project_name in self._current_tasks
        if is_busy:
            return SubmitResult(
                status="conflict",
                message=(
                    f"项目 '{project_name}' 正在执行任务，"
                    "请选择: 排队(queue) / 打断(interrupt) / 取消(cancel)"
                ),
            )

        record = TaskRecord(prompt=prompt, status="queued", session_id=session.active_session_id)
        queued = QueuedTask(prompt=prompt, record=record, priority=0)
        queue = self._ensure_queue(project_name)
        await queue.put((queued.priority, time.monotonic(), queued))
        self._ensure_worker(project_name)
        return SubmitResult(
            status="submitted",
            message=f"任务已提交到项目 '{project_name}' (#{record.id})",
            task_id=record.id,
        )

    async def enqueue_task(self, project_name: str, prompt: str) -> SubmitResult:
        """Force-enqueue regardless of current state."""
        session = self.get_session(project_name)
        if not session:
            return SubmitResult(status="error", message=f"错误: 项目 '{project_name}' 不存在")

        record = TaskRecord(prompt=prompt, status="queued", session_id=session.active_session_id)
        queued = QueuedTask(prompt=prompt, record=record, priority=0)
        queue = self._ensure_queue(project_name)
        await queue.put((queued.priority, time.monotonic(), queued))
        self._ensure_worker(project_name)

        position = queue.qsize()
        return SubmitResult(
            status="queued",
            message=f"任务 #{record.id} 已加入队列 (排队位置: {position})",
            task_id=record.id,
            queue_position=position,
        )

    async def interrupt_and_submit(self, project_name: str, prompt: str) -> SubmitResult:
        """Interrupt the current task and insert *prompt* at the front of the queue."""
        session = self.get_session(project_name)
        if not session:
            return SubmitResult(status="error", message=f"错误: 项目 '{project_name}' 不存在")

        record = TaskRecord(prompt=prompt, status="queued", session_id=session.active_session_id)
        queued = QueuedTask(prompt=prompt, record=record, priority=-1)
        queue = self._ensure_queue(project_name)
        # Enqueue first so the task is safe even if interrupt raises.
        await queue.put((queued.priority, time.monotonic(), queued))
        self._ensure_worker(project_name)

        # Interrupt the running SDK call; consume_response will end and the
        # worker loop picks up the next (high-priority) item.
        if session.task_state == TaskState.RUNNING:
            await session.interrupt()

        return SubmitResult(
            status="submitted",
            message=f"已中断当前任务，新任务 #{record.id} 将优先执行",
            task_id=record.id,
        )

    async def interrupt_task(self, project_name: str) -> str:
        """Interrupt the running task for a project (no new task enqueued)."""
        session = self._sessions.get(project_name)
        if not session:
            return f"项目 '{project_name}' 无活跃会话"
        if session.task_state != TaskState.RUNNING:
            return f"项目 '{project_name}' 当前无运行中的任务"
        await session.interrupt()
        return f"已中断项目 '{project_name}' 的任务"

    # ── Queue queries ──────────────────────────────────────────────

    def get_queue_info(self, project_name: str) -> list[QueuedTask]:
        queue = self._queues.get(project_name)
        if not queue:
            return []
        # PriorityQueue stores items in _queue (internal list).
        return [item[2] for item in list(queue._queue)]  # noqa: SLF001

    def cancel_queued(self, project_name: str, task_id: str) -> bool:
        """Remove a queued (not yet running) task by id. Returns True on success."""
        queue = self._queues.get(project_name)
        if not queue:
            return False
        # PriorityQueue doesn't support removal; rebuild.
        original = list(queue._queue)  # noqa: SLF001
        remaining = [item for item in original if item[2].record.id != task_id]
        if len(remaining) == len(original):
            return False
        queue._queue.clear()  # noqa: SLF001
        for item in remaining:
            queue._queue.append(item)  # noqa: SLF001
        queue._queue.sort()  # noqa: SLF001
        return True

    # ── Worker loop ────────────────────────────────────────────────

    async def _worker_loop(self, project_name: str) -> None:
        """Long-lived consumer for one project's task queue.

        The worker keeps the SDK connection alive across consecutive tasks and
        only disconnects after an idle timeout or when the worker is cancelled.
        """
        queue = self._ensure_queue(project_name)
        idle_timeout = self._policy.idle_disconnect_seconds

        try:
            while True:
                # Wait for the next task, disconnecting on idle timeout.
                try:
                    _, _, queued = await asyncio.wait_for(queue.get(), timeout=idle_timeout)
                except asyncio.TimeoutError:
                    session = self._sessions.get(project_name)
                    if session:
                        try:
                            await session.disconnect()
                        except Exception:
                            pass
                    continue

                self._current_tasks[project_name] = queued
                try:
                    await self._run_task_item(project_name, queued)
                except asyncio.CancelledError:
                    # Worker itself is being shut down.
                    queued.record.status = "cancelled"
                    queued.record.completed_at = datetime.now()
                    self._persist_task(project_name, queued.record)
                    raise
                except Exception:
                    logger.opt(exception=True).warning(
                        "Unhandled error in worker for '{}'", project_name
                    )
                finally:
                    self._current_tasks.pop(project_name, None)
                    queue.task_done()

                # Check session rotation after each task.
                if self._should_rotate(project_name):
                    await self._rotate_session(project_name)
        except asyncio.CancelledError:
            pass
        finally:
            self._workers.pop(project_name, None)

    async def _run_task_item(self, project_name: str, queued: QueuedTask) -> None:
        session = self._sessions[project_name]
        record = queued.record
        record.status = "running"
        session.project.current_task = record
        session.task_state = TaskState.RUNNING

        try:
            client = await session.ensure_connected()
            await client.query(queued.prompt)
            result = await session.consume_response()

            # session.interrupt() may cause consume_response to end gracefully
            # (returning None) rather than raising CancelledError.
            if session.task_state in (TaskState.INTERRUPTING, TaskState.CANCELLED):
                session.task_state = TaskState.INTERRUPTED
                record.status = "interrupted"
                await self._notify(project_name, compose_task_interrupted(project_name))
                return

            session.task_state = TaskState.COMPLETED
            cost = result.get("cost", 0.0) if result else 0.0
            record.status = "completed"
            record.cost_usd = cost
            record.session_id = result.get("session_id") if result else record.session_id
            await self._notify(project_name, compose_task_completed(project_name, cost))
        except asyncio.CancelledError:
            session.task_state = TaskState.INTERRUPTED
            record.status = "interrupted"
            await self._notify(project_name, compose_task_interrupted(project_name))
        except Exception as exc:
            if self._is_context_too_long(exc):
                await self._handle_context_too_long(project_name, session, queued, exc)
                return
            if self._is_process_error(exc):
                await self._handle_process_error(project_name, session, queued, exc)
                return
            session.task_state = TaskState.FAILED
            record.status = "failed"
            record.error = str(exc)[:500]
            await self._notify(project_name, compose_task_failed(project_name, str(exc)))
        finally:
            record.completed_at = datetime.now()
            self._persist_task(project_name, record)
            session.project.current_task = None

    # ── Session rotation / context-too-long ────────────────────────

    def _should_rotate(self, project_name: str) -> bool:
        session_log = self.get_session_log(project_name)
        if not session_log:
            return False
        active = session_log.active()
        if not active:
            return False
        return (
            len(active.task_ids) >= self._policy.max_tasks_per_session
            or active.total_cost_usd >= self._policy.max_cost_per_session
        )

    async def _rotate_session(self, project_name: str) -> None:
        session = self._sessions.get(project_name)
        if not session:
            return
        self.close_session(project_name)
        try:
            await session.disconnect()
        except Exception:
            pass
        session.active_session_id = None
        session.task_state = TaskState.IDLE
        await self._notify(project_name, compose_session_rotated(project_name, "idle"))

    @staticmethod
    def _is_process_error(exc: Exception) -> bool:
        try:
            from claude_agent_sdk import ProcessError
            if isinstance(exc, ProcessError):
                return True
        except ImportError:
            pass
        msg = str(exc).lower()
        return any(marker in msg for marker in _PROCESS_ERROR_MARKERS)

    @staticmethod
    def _is_context_too_long(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(marker in msg for marker in _CONTEXT_TOO_LONG_MARKERS)

    async def _handle_context_too_long(
        self,
        project_name: str,
        session: ProjectSession,
        queued: QueuedTask,
        original_exc: Exception,
    ) -> None:
        record = queued.record
        await self._notify(project_name, compose_session_rotated(project_name, "context_too_long"))
        await self._rotate_session(project_name)

        try:
            session.task_state = TaskState.RUNNING
            client = await session.ensure_connected()
            await client.query(queued.prompt)
            result = await session.consume_response()

            session.task_state = TaskState.COMPLETED
            cost = result.get("cost", 0.0) if result else 0.0
            record.status = "completed"
            record.cost_usd = cost
            record.session_id = result.get("session_id") if result else record.session_id
            await self._notify(project_name, compose_retry_success(project_name, cost))
        except Exception as retry_exc:
            session.task_state = TaskState.FAILED
            record.status = "failed"
            record.error = f"重试失败: {retry_exc}"[:500]
            await self._notify(project_name, compose_retry_failed(project_name, str(retry_exc)))

    async def _handle_process_error(
        self,
        project_name: str,
        session: ProjectSession,
        queued: QueuedTask,
        original_exc: Exception,
    ) -> None:
        """Handle a dead Claude Code process by resetting the connection and retrying."""
        record = queued.record
        had_resume = session.active_session_id is not None
        logger.warning(
            "Process error for '{}' (resume={}): {}",
            project_name,
            session.active_session_id and session.active_session_id[:8],
            original_exc,
        )
        await self._notify(
            project_name,
            compose_session_rotated(project_name, "process_error"),
        )

        self.close_session(project_name)
        try:
            await session.disconnect()
        except Exception:
            pass
        if had_resume:
            session.active_session_id = None

        try:
            session.task_state = TaskState.RUNNING
            client = await session.ensure_connected()
            await client.query(queued.prompt)
            result = await session.consume_response()

            session.task_state = TaskState.COMPLETED
            cost = result.get("cost", 0.0) if result else 0.0
            record.status = "completed"
            record.cost_usd = cost
            record.session_id = result.get("session_id") if result else record.session_id
            await self._notify(project_name, compose_retry_success(project_name, cost))
        except Exception as retry_exc:
            session.task_state = TaskState.FAILED
            record.status = "failed"
            record.error = f"进程异常重试失败: {retry_exc}"[:500]
            await self._notify(project_name, compose_retry_failed(project_name, str(retry_exc)))

    # ── Status queries ─────────────────────────────────────────────

    def get_task_status(self, project_name: str) -> str:
        session = self._sessions.get(project_name)
        if not session:
            return "无活跃会话"
        queue = self._queues.get(project_name)
        queued_count = queue.qsize() if queue else 0
        status = session.task_state.value
        if queued_count:
            status += f" (队列中 {queued_count} 个待执行)"
        return status

    def get_all_status(self) -> dict[str, str]:
        return {name: self.get_task_status(name) for name in self._sessions}

    # ── Shutdown ───────────────────────────────────────────────────

    async def shutdown(self) -> None:
        workers = list(self._workers.values())
        for w in workers:
            w.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

        for session in self._sessions.values():
            try:
                await session.disconnect()
            except Exception:
                pass

        self._sessions.clear()
        self._workers.clear()
        self._queues.clear()
        self._current_tasks.clear()

    # ── Helpers ────────────────────────────────────────────────────

    def _persist_task(self, project_name: str, record: TaskRecord) -> None:
        task_log = self.get_task_log(project_name)
        if task_log:
            task_log.append(record)
        self._update_session(project_name, record)

    async def _notify(self, project_name: str, message: str | RichMessage) -> None:
        if self._on_notify:
            try:
                await self._on_notify(project_name, message)
            except Exception:
                pass

    def _build_permission_handler(self):
        return None
