from __future__ import annotations

import asyncio

from chatcc.agent.dispatcher import AgentDeps, Dispatcher
from chatcc.agent.provider import build_model_from_config
from chatcc.approval.table import ApprovalTable
from chatcc.channel.base import MessageChannel
from chatcc.channel.factory import create_channel
from chatcc.channel.message import InboundMessage, OutboundMessage
from chatcc.claude.task_manager import TaskManager
from chatcc.command.commands import get_builtin_commands
from chatcc.command.registry import CommandRegistry
from chatcc.config import CHATCC_HOME, AppConfig, load_config
from chatcc.cost.tracker import CostTracker
from chatcc.memory.history import ConversationHistory
from chatcc.memory.longterm import LongTermMemory
from chatcc.memory.summary import SummaryManager
from chatcc.project.manager import ProjectManager
from chatcc.router.router import MessageRouter, RouteResult
from chatcc.service.manager import ServiceManager

from loguru import logger


class Application:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()

        # Core subsystems
        self.project_manager = ProjectManager(
            data_dir=CHATCC_HOME / "projects",
            workspace_root=self.config.security.workspace_root,
            claude_defaults=self.config.claude_defaults,
        )
        self.approval_table = ApprovalTable()
        self.cost_tracker = CostTracker(budget_limit=self.config.budget.daily_limit)
        self.history = ConversationHistory(storage_dir=CHATCC_HOME / "history")
        self.longterm_memory = LongTermMemory(
            memory_dir=CHATCC_HOME / "memory",
            recent_days=self.config.agent.memory.get("recent_daily_notes", 3),
        )
        self.summary_manager = SummaryManager(
            history=self.history,
            longterm_memory=self.longterm_memory,
            config=self.config.agent.memory,
        )
        self.service_manager = ServiceManager(services_dir=CHATCC_HOME / "services")
        self.task_manager = TaskManager(
            project_manager=self.project_manager,
            approval_table=self.approval_table,
            on_notify=self._on_claude_notify,
            dangerous_patterns=self.config.security.dangerous_tool_patterns,
        )

        # Command system
        self.command_registry = CommandRegistry()
        self.command_registry.register_many(get_builtin_commands())

        # Channel and routing
        self.channel: MessageChannel | None = None
        self.router = MessageRouter(registry=self.command_registry)
        self.dispatcher: Dispatcher | None = None
        self._running = False
        self._last_chat_id: str | None = None

    async def _on_claude_notify(self, project_name: str, message: str) -> None:
        if self.channel and self._last_chat_id:
            await self.channel.send(
                OutboundMessage(
                    chat_id=self._last_chat_id,
                    content=f"[{project_name}] {message}",
                )
            )

    async def start(self):
        logger.info("Starting ChatCC...")

        if not self._init_channel():
            return

        self._init_dispatcher()
        self.channel.on_message(self._on_message)

        self._running = True
        await self.channel.start()
        await self.channel.register_commands(self.command_registry.all_specs)

        logger.info(f"ChatCC running with channel: {self.config.channel.type}")

        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop()

    async def stop(self):
        self._running = False
        if self.task_manager:
            await self.task_manager.shutdown()
        if self.service_manager:
            await self.service_manager.stop_all()
        if self.channel:
            await self.channel.stop()
        logger.info("ChatCC stopped.")

    def _init_channel(self) -> bool:
        self.channel = create_channel(self.config.channel)
        if not self.channel.is_authenticated():
            logger.error(
                f"Channel '{self.config.channel.type}' not authenticated. "
                f"Run: chatcc auth --channel {self.config.channel.type}"
            )
            return False
        return True

    def _init_dispatcher(self):
        if not self.config.agent.providers:
            logger.warning("No AI providers configured, dispatcher not initialized")
            return
        try:
            model = build_model_from_config(
                self.config.agent.providers,
                self.config.agent.active_provider,
            )
            self.dispatcher = Dispatcher(
                provider_name=self.config.agent.active_provider,
                model_id=model,
                persona=self.config.agent.persona,
            )
        except KeyError:
            logger.warning(
                f"Provider '{self.config.agent.active_provider}' not found in config"
            )

    # ── Message routing ──────────────────────────────────────────────

    async def _on_message(self, message: InboundMessage):
        result = await self.router.route(message)

        if result.intercepted:
            await self._handle_intercept(result, message)
        elif result.augmented:
            await self._handle_augmented(result, message)
        else:
            await self._handle_agent_message(message)

    # ── Intercept commands (bypass agent, instant response) ──────────

    async def _handle_intercept(
        self, result: RouteResult, message: InboundMessage
    ):
        command = result.command
        args = result.args

        match command:
            case "/y":
                if args and args[0] == "all":
                    count = self.approval_table.approve_all()
                    response = f"已全部确认 ({count} 条)"
                elif args:
                    try:
                        aid = int(args[0])
                        if self.approval_table.approve(aid):
                            response = f"已确认 #{aid}"
                        else:
                            response = f"#{aid} 不存在或已处理"
                    except ValueError:
                        response = f"无效的审批 ID: {args[0]}"
                else:
                    if self.approval_table.approve_oldest():
                        response = "已确认最早的待审批项"
                    else:
                        response = "暂无待确认操作"

            case "/n":
                if args and args[0] == "all":
                    count = self.approval_table.deny_all()
                    response = f"已全部拒绝 ({count} 条)"
                elif args:
                    try:
                        aid = int(args[0])
                        if self.approval_table.deny(aid):
                            response = f"已拒绝 #{aid}"
                        else:
                            response = f"#{aid} 不存在或已处理"
                    except ValueError:
                        response = f"无效的审批 ID: {args[0]}"
                else:
                    if self.approval_table.deny_oldest():
                        response = "已拒绝最早的待审批项"
                    else:
                        response = "暂无待确认操作"

            case "/pending":
                pending = self.approval_table.list_pending()
                if not pending:
                    response = "暂无待确认操作"
                else:
                    lines = [f"待确认操作 ({len(pending)} 条):"]
                    for p in pending:
                        lines.append(
                            f"  #{p.id} [{p.project}] {p.tool_name}: {p.input_summary}"
                        )
                    response = "\n".join(lines)

            case "/help":
                response = self.command_registry.help_text()

            case _:
                response = f"未知命令: {command}"

        await self.channel.send(
            OutboundMessage(chat_id=message.chat_id, content=response)
        )

    # ── Augmented commands (prompt injection → agent) ────────────────

    async def _handle_augmented(
        self, result: RouteResult, message: InboundMessage
    ):
        if not self.dispatcher:
            await self.channel.send(
                OutboundMessage(
                    chat_id=message.chat_id,
                    content="AI 供应商未配置，无法处理消息",
                )
            )
            return

        self._last_chat_id = message.chat_id
        await self.channel.send_typing(message.chat_id)

        self.history.add_message("user", message.content)

        deps = AgentDeps(
            project_manager=self.project_manager,
            approval_table=self.approval_table,
            cost_tracker=self.cost_tracker,
            history=self.history,
            longterm_memory=self.longterm_memory,
            task_manager=self.task_manager,
            service_manager=self.service_manager,
            send_fn=self._send_to_channel,
            chat_id=message.chat_id,
        )

        agent_input = result.augmented_prompt or message.content

        try:
            run_result = await self.dispatcher.agent.run(agent_input, deps=deps)
            response_text = run_result.output

            self.history.add_message("assistant", response_text)

            if self.summary_manager.should_compress():
                asyncio.create_task(self._compress_history())

            await self.channel.send(
                OutboundMessage(chat_id=message.chat_id, content=response_text)
            )
        except Exception as e:
            from pydantic_ai.exceptions import UnexpectedModelBehavior
            if isinstance(e, UnexpectedModelBehavior):
                logger.error("Agent error: {}", e)
            else:
                logger.exception("Agent error")
            await self.channel.send(
                OutboundMessage(
                    chat_id=message.chat_id, content=f"处理消息时出错: {e}"
                )
            )

    # ── Normal agent message (passthrough) ───────────────────────────

    async def _handle_agent_message(self, message: InboundMessage):
        if not self.dispatcher:
            await self.channel.send(
                OutboundMessage(
                    chat_id=message.chat_id,
                    content="AI 供应商未配置，无法处理消息",
                )
            )
            return

        self._last_chat_id = message.chat_id
        await self.channel.send_typing(message.chat_id)

        self.history.add_message("user", message.content)

        deps = AgentDeps(
            project_manager=self.project_manager,
            approval_table=self.approval_table,
            cost_tracker=self.cost_tracker,
            history=self.history,
            longterm_memory=self.longterm_memory,
            task_manager=self.task_manager,
            service_manager=self.service_manager,
            send_fn=self._send_to_channel,
            chat_id=message.chat_id,
        )

        try:
            result = await self.dispatcher.agent.run(message.content, deps=deps)
            response_text = result.output

            self.history.add_message("assistant", response_text)

            if self.summary_manager.should_compress():
                asyncio.create_task(self._compress_history())

            await self.channel.send(
                OutboundMessage(chat_id=message.chat_id, content=response_text)
            )
        except Exception as e:
            from pydantic_ai.exceptions import UnexpectedModelBehavior
            if isinstance(e, UnexpectedModelBehavior):
                logger.error("Agent error: {}", e)
            else:
                logger.exception("Agent error")
            await self.channel.send(
                OutboundMessage(
                    chat_id=message.chat_id, content=f"处理消息时出错: {e}"
                )
            )

    # ── Helpers ──────────────────────────────────────────────────────

    async def _compress_history(self) -> None:
        try:
            summary = await self.summary_manager.compress()
            if summary:
                logger.info("History compressed: {}", summary[:100])
        except Exception:
            logger.exception("Failed to compress history")

    async def _send_to_channel(self, message: OutboundMessage) -> None:
        if self.channel:
            await self.channel.send(message)
