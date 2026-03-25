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

    async def consume_response(self) -> dict[str, Any] | None:
        """Consume Claude Code response stream, forwarding notifications to IM.

        Returns the final result or None if interrupted/failed.
        """
        if not self.client:
            return None

        result: dict[str, Any] | None = None
        try:
            async for message in self.client.receive_response():
                msg_type = getattr(message, "type", None)

                if msg_type == "assistant":
                    content_blocks = getattr(message, "content", [])
                    for block in content_blocks:
                        text = getattr(block, "text", None)
                        if text and self._on_notification:
                            await self._on_notification(self.project.name, text)
                elif msg_type == "result":
                    self.task_state = TaskState.COMPLETED
                    result = {
                        "type": "result",
                        "session_id": getattr(
                            message, "session_id", self.active_session_id
                        ),
                        "cost": getattr(message, "cost_usd", 0.0),
                    }
                    sid = getattr(message, "session_id", None)
                    if sid:
                        self.active_session_id = sid
                    break
        except asyncio.CancelledError:
            self.task_state = TaskState.CANCELLED
            raise
        except Exception:
            self.task_state = TaskState.FAILED
            raise

        return result

    async def send_task(self, prompt: str) -> dict[str, Any] | None:
        """Send a task and consume the response stream."""
        client = await self.ensure_connected()
        self.task_state = TaskState.RUNNING
        try:
            await client.query(prompt)
            return await self.consume_response()
        except asyncio.CancelledError:
            self.task_state = TaskState.CANCELLED
            raise
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
