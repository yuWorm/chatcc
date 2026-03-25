from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from chatcc.channel.message import InboundMessage, OutboundMessage, RichMessage


class MessageChannel(ABC):

    @abstractmethod
    async def start(self) -> None:
        """启动渠道连接"""

    @abstractmethod
    async def stop(self) -> None:
        """断开连接，清理资源"""

    @abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """发送消息到渠道"""

    @abstractmethod
    def render(self, message: RichMessage) -> Any:
        """将 RichMessage 转为渠道原生消息格式"""

    @abstractmethod
    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        """注册消息回调"""

    def register_auth_commands(self, cli_group: Any) -> None:
        """注册渠道认证相关的 CLI 子命令 (可选)"""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """检查渠道是否已完成认证"""
