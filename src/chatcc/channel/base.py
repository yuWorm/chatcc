from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from chatcc.channel.message import InboundMessage, OutboundMessage, RichMessage

if TYPE_CHECKING:
    from chatcc.setup.ui import SetupUI


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

    @staticmethod
    def interactive_setup(
        ui: SetupUI,
        *,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """交互式凭证收集。返回写入 config.yaml 的渠道配置字典。

        existing 为当前已有配置，用于增量修改时填充默认值。
        子类应覆写此方法。未覆写的渠道 (如 CLI) 无需配置。
        """
        return {}

    @abstractmethod
    def is_authenticated(self) -> bool:
        """检查渠道是否已完成认证"""

    async def send_typing(self, chat_id: str) -> None:
        """发送"正在输入"状态提示。不支持的渠道默认忽略。"""
