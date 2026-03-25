from __future__ import annotations

import asyncio
import logging

from chatcc.config import AppConfig, load_config
from chatcc.channel.base import MessageChannel
from chatcc.channel.factory import create_channel
from chatcc.channel.message import InboundMessage, OutboundMessage
from chatcc.router.router import MessageRouter
from chatcc.agent.dispatcher import Dispatcher, AgentDeps
from chatcc.agent.provider import build_model_from_config

logger = logging.getLogger("chatcc")


class Application:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.channel: MessageChannel | None = None
        self.router = MessageRouter()
        self.dispatcher: Dispatcher | None = None
        self._running = False

    async def start(self):
        logger.info("Starting ChatCC...")

        if not self._init_channel():
            return

        self._init_dispatcher()
        self.channel.on_message(self._on_message)

        self._running = True
        await self.channel.start()

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

    async def _on_message(self, message: InboundMessage):
        result = await self.router.route(message)

        if result.intercepted:
            await self._handle_command(result.command, result.args, message)
        else:
            await self._handle_agent_message(message)

    async def _handle_command(
        self, command: str, args: list[str], message: InboundMessage
    ):
        match command:
            case "/y" | "/n":
                response = f"审批命令 {command} {' '.join(args)} (待实现)"
            case "/pending":
                response = "暂无待确认操作 (待实现)"
            case "/stop":
                response = "停止命令已收到 (待实现)"
            case "/status":
                response = "系统状态: 正常运行中"
            case _:
                response = f"未知命令: {command}"

        await self.channel.send(
            OutboundMessage(chat_id=message.chat_id, content=response)
        )

    async def _handle_agent_message(self, message: InboundMessage):
        if not self.dispatcher:
            await self.channel.send(
                OutboundMessage(
                    chat_id=message.chat_id,
                    content="AI 供应商未配置，无法处理消息",
                )
            )
            return

        deps = AgentDeps(chat_id=message.chat_id)

        try:
            result = await self.dispatcher.agent.run(message.content, deps=deps)
            await self.channel.send(
                OutboundMessage(chat_id=message.chat_id, content=result.output)
            )
        except Exception as e:
            logger.exception("Agent error")
            await self.channel.send(
                OutboundMessage(
                    chat_id=message.chat_id, content=f"处理消息时出错: {e}"
                )
            )
