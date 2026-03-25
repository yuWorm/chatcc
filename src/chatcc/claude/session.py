from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from enum import Enum
from typing import Any

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, HookMatcher

from chatcc.project.models import Project


class TaskState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ProjectSession:
    def __init__(
        self,
        project: Project,
        on_notification: Callable[[str, str], Awaitable[None]] | None = None,
        on_permission: Callable[[str, dict], Awaitable[bool]] | None = None,
    ):
        self.project = project
        self.client: ClaudeSDKClient | None = None
        self.active_session_id: str | None = None
        self.task_state: TaskState = TaskState.IDLE
        self._on_notification = on_notification
        self._on_permission = on_permission

    def _build_options(self) -> ClaudeAgentOptions:
        hooks = {}
        if self._on_notification:
            hooks["Notification"] = [HookMatcher(hooks=[self._notification_hook])]

        return ClaudeAgentOptions(
            cwd=self.project.path,
            permission_mode=self.project.config.permission_mode,
            setting_sources=self.project.config.setting_sources,
            can_use_tool=self._permission_handler if self._on_permission else None,
            hooks=hooks if hooks else None,
            resume=self.active_session_id,
            model=self.project.config.model,
        )

    async def ensure_connected(self) -> ClaudeSDKClient:
        if not self.client:
            self.client = ClaudeSDKClient(options=self._build_options())
            await self.client.connect()
        return self.client

    async def send_task(self, prompt: str) -> None:
        client = await self.ensure_connected()
        self.task_state = TaskState.RUNNING
        try:
            await client.query(prompt)
        except Exception:
            self.task_state = TaskState.FAILED
            raise

    async def interrupt(self) -> None:
        if self.client and self.task_state == TaskState.RUNNING:
            self.task_state = TaskState.INTERRUPTING
            await self.client.interrupt()

    async def disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def _notification_hook(self, context: Any) -> None:
        if self._on_notification:
            title = getattr(context, "title", "")
            body = getattr(context, "body", "")
            await self._on_notification(self.project.name, f"{title}: {body}")

    async def _permission_handler(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        if self._on_permission:
            allowed = await self._on_permission(tool_name, input_data)
            if allowed:
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(reason="User denied")
        return PermissionResultAllow(updated_input=input_data)
