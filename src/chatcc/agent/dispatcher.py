from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext

from chatcc.agent.prompt import build_system_prompt
from chatcc.tools.command_tools import register_command_tools
from chatcc.tools.project_tools import register_project_tools
from chatcc.tools.service_tools import register_service_tools


@dataclass
class AgentDeps:
    """主 Agent 运行时依赖 — 所有子模块引用"""

    project_manager: Any = None  # chatcc.project.manager.ProjectManager
    approval_table: Any = None  # chatcc.approval.table.ApprovalTable
    cost_tracker: Any = None  # chatcc.cost.tracker.CostTracker
    history: Any = None  # chatcc.memory.history.ConversationHistory
    longterm_memory: Any = None  # chatcc.memory.longterm.LongTermMemory
    task_manager: Any = None  # will be chatcc.claude.task_manager.TaskManager
    service_manager: Any = None  # will be chatcc.service.manager.ServiceManager
    send_fn: Any = None  # Callable[[OutboundMessage], Awaitable[None]]
    chat_id: str = ""  # current message source chat_id


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
        deps = ctx.deps
        default_project = None
        active_count = 0
        pending_count = 0
        memory_context = ""

        if deps.project_manager:
            dp = deps.project_manager.default_project
            default_project = dp.name if dp else None
            active_count = deps.project_manager.active_count
        if deps.approval_table:
            pending_count = deps.approval_table.pending_count
        if deps.longterm_memory:
            memory_context = deps.longterm_memory.get_context()

        return build_system_prompt(
            persona_name=self.persona,
            default_project=default_project,
            active_count=active_count,
            pending_count=pending_count,
            memory_context=memory_context,
        )

    def _register_tools(self) -> None:
        register_project_tools(self.agent)
        register_command_tools(self.agent)
        register_service_tools(self.agent)
