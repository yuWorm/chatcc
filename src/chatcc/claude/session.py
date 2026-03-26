from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from enum import Enum
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
)
from claude_agent_sdk.types import HookContext, HookInput, SyncHookJSONOutput
from loguru import logger

from chatcc.project.models import Project

if TYPE_CHECKING:
    from chatcc.approval.table import ApprovalTable


class TaskState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


def _summarize_tool_input(tool_name: str, input_data: dict[str, Any]) -> str:
    """Create a short summary of the tool input for approval messages."""
    if tool_name == "Bash":
        return input_data.get("command", str(input_data))[:200]
    if tool_name == "Write":
        path = input_data.get("path", "unknown")
        return f"写入文件: {path}"
    return f"{tool_name}({str(input_data)[:150]})"


class ProjectSession:
    def __init__(
        self,
        project: Project,
        on_notification: Callable[[str, str], Awaitable[None]] | None = None,
        on_permission: Callable[[str, dict], Awaitable[bool]] | None = None,
        approval_table: ApprovalTable | None = None,
        dangerous_patterns: dict[str, list[str]] | None = None,
    ):
        self.project = project
        self.client: ClaudeSDKClient | None = None
        self.active_session_id: str | None = None
        self.task_state: TaskState = TaskState.IDLE
        self._on_notification = on_notification
        self._on_permission = on_permission
        self._approval_table = approval_table
        self._dangerous_patterns = dangerous_patterns

    def _build_options(self) -> ClaudeAgentOptions:
        hooks = {}
        if self._on_notification:
            hooks["Notification"] = [HookMatcher(hooks=[self._notification_hook])]
            hooks["Stop"] = [HookMatcher(hooks=[self._stop_hook])]

        has_permission_handling = self._approval_table or self._on_permission
        return ClaudeAgentOptions(
            cwd=self.project.path,
            permission_mode=self.project.config.permission_mode,
            setting_sources=self.project.config.setting_sources,
            can_use_tool=self._permission_handler if has_permission_handling else None,
            hooks=hooks if hooks else None,
            resume=self.active_session_id,
            model=self.project.config.model,
            stderr=self._stderr_handler,
        )

    async def ensure_connected(self) -> ClaudeSDKClient:
        if not self.client:
            client = ClaudeSDKClient(options=self._build_options())
            try:
                await client.connect()
            except Exception:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                raise
            self.client = client
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
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text:
                            if self._on_notification:
                                await self._on_notification(
                                    self.project.name, block.text
                                )
                elif isinstance(message, ResultMessage):
                    self.task_state = TaskState.COMPLETED
                    result = {
                        "type": "result",
                        "session_id": message.session_id
                        or self.active_session_id,
                        "cost": message.total_cost_usd or 0.0,
                    }
                    if message.session_id:
                        self.active_session_id = message.session_id
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
        client = self.client
        self.client = None
        if client:
            await client.disconnect()

    def _stderr_handler(self, line: str) -> None:
        logger.debug("Claude CLI [{}]: {}", self.project.name, line.rstrip())

    async def _notification_hook(
        self, input: HookInput, tool_use_id: str | None, context: HookContext
    ) -> SyncHookJSONOutput:
        if self._on_notification:
            title = input.get("title", "")  # type: ignore[union-attr]
            body = input.get("message", "")  # type: ignore[union-attr]
            await self._on_notification(self.project.name, f"{title}: {body}")
        return SyncHookJSONOutput()

    async def _stop_hook(
        self, input: HookInput, tool_use_id: str | None, context: HookContext
    ) -> SyncHookJSONOutput:
        self.task_state = TaskState.COMPLETED
        return SyncHookJSONOutput()

    async def _permission_handler(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        from chatcc.approval.risk import assess_risk

        risk = assess_risk(
            tool_name, input_data, project_path=self.project.path,
            dangerous_patterns=self._dangerous_patterns,
        )

        if risk == "safe":
            return PermissionResultAllow(updated_input=input_data)

        if risk == "forbidden":
            return PermissionResultDeny(reason="操作超出项目目录边界")

        # risk == "dangerous"
        if self._approval_table and self._on_notification:
            summary = _summarize_tool_input(tool_name, input_data)
            future = self._approval_table.request_approval(
                self.project.name, tool_name, summary
            )
            await self._on_notification(
                self.project.name,
                f"⚠️ 危险操作待确认:\n{tool_name}: {summary}\n回复 /y 确认 或 /n 拒绝",
            )
            allowed = await future
            if allowed:
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(reason="用户拒绝")

        if self._on_permission:
            allowed = await self._on_permission(tool_name, input_data)
            if allowed:
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(reason="User denied")

        return PermissionResultDeny(reason="无审批机制，拒绝危险操作")
