from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext

from chatcc.agent.prompt import build_system_prompt


@dataclass
class AgentDeps:
    """主 Agent 运行时依赖"""
    default_project: str | None = None
    active_projects: int = 0
    pending_approvals: int = 0
    send_fn: Any = None


class Dispatcher:
    def __init__(
        self,
        provider_name: str,
        model_id: str | Any,
        persona: str = "default",
    ):
        self.provider_name = provider_name
        self.persona = persona

        self.agent = Agent(
            model_id,
            deps_type=AgentDeps,
            instructions=self._build_instructions,
        )

        self._register_tools()

    def _build_instructions(self, ctx: RunContext[AgentDeps]) -> str:
        return build_system_prompt(
            persona_name=self.persona,
            default_project=ctx.deps.default_project,
            active_count=ctx.deps.active_projects,
            pending_count=ctx.deps.pending_approvals,
        )

    def _register_tools(self):
        @self.agent.tool_plain
        def send_message(content: str) -> str:
            """发送消息到 IM 渠道 (用于主动通知)"""
            return f"[send_message] {content}"

        @self.agent.tool_plain
        def get_status() -> str:
            """获取当前系统状态"""
            return "系统状态: 正常运行中"
