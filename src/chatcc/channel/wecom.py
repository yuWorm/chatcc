"""WeCom (企业微信) AI Bot channel — WebSocket long-connection via wecom-aibot-sdk."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from loguru import logger
from wecom_aibot_sdk import WSClient

from chatcc.channel.base import MessageChannel
from chatcc.channel.message import (
    ActionGroup,
    CodeElement,
    DividerElement,
    InboundMessage,
    OutboundMessage,
    ProgressElement,
    RichMessage,
    TextElement,
)

if TYPE_CHECKING:
    from chatcc.setup.ui import SetupUI


class WeComChannel(MessageChannel):

    @staticmethod
    def interactive_setup(
        ui: SetupUI,
        *,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import questionary as q

        ex = existing or {}
        has_existing = existing is not None

        q.print("=== 企业微信智能机器人认证 ===", style="bold fg:cyan")
        bot_id = ui.prompt("请输入 Bot ID (机器人 ID)", default=ex.get("bot_id", ""))

        new_secret = ui.prompt_secret("请输入 Bot Secret", has_existing=has_existing)
        secret = new_secret if new_secret is not None else ex.get("secret", "")

        if not bot_id or not secret:
            raise ValueError("Bot ID 和 Secret 不能为空")

        default_allowed = ",".join(str(u) for u in ex.get("allowed_users", []))
        allowed = ui.prompt(
            "允许的用户 ID (逗号分隔, 留空允许所有)",
            default=default_allowed,
        )
        allowed_list = [u.strip() for u in allowed.split(",") if u.strip()]

        return {
            "bot_id": bot_id,
            "secret": secret,
            "allowed_users": allowed_list,
        }

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._bot_id: str = config.get("bot_id", "")
        self._secret: str = config.get("secret", "")
        self._allowed_users: list[str] = [
            str(u) for u in config.get("allowed_users", [])
        ]
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._ws_client: WSClient | None = None

    async def start(self) -> None:
        if not self._bot_id or not self._secret:
            raise RuntimeError("WeCom bot_id/secret not configured")

        self._ws_client = WSClient(
            bot_id=self._bot_id,
            secret=self._secret,
            max_reconnect_attempts=-1,
        )

        self._ws_client.on("message.text", self._on_text)
        self._ws_client.on("message.mixed", self._on_text)
        self._ws_client.on("event.template_card_event", self._on_card_event)

        await self._ws_client.connect()
        logger.info("WeCom channel started (WebSocket)")

    async def stop(self) -> None:
        if self._ws_client:
            await self._ws_client.disconnect()
        logger.info("WeCom channel stopped")

    async def send(self, message: OutboundMessage) -> None:
        if not self._ws_client:
            raise RuntimeError("WeCom client not connected")

        if isinstance(message.content, RichMessage):
            payload = self.render(message.content)
        else:
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": str(message.content)},
            }

        await self._ws_client.send_message(message.chat_id, payload)

    def render(self, message: RichMessage) -> dict[str, Any]:
        text_parts: list[str] = []
        buttons: list[dict[str, Any]] = []

        for el in message.elements:
            match el:
                case TextElement(content=content):
                    text_parts.append(content)
                case CodeElement(code=code, language=lang):
                    text_parts.append(f"```{lang}\n{code}\n```")
                case ActionGroup(buttons=action_buttons):
                    for b in action_buttons:
                        style = 1 if "/y" in b.command or b.style == "primary" else 2
                        buttons.append({
                            "text": b.label,
                            "style": style,
                            "key": b.command,
                        })
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    text_parts.append(f"⏳ {tag}{desc}")
                case DividerElement():
                    text_parts.append("---")

        body_text = "\n\n".join(text_parts)

        if buttons:
            title = f"[{message.project_tag}] ChatCC" if message.project_tag else "ChatCC"
            return {
                "msgtype": "template_card",
                "template_card": {
                    "card_type": "button_interaction",
                    "main_title": {"title": title},
                    "sub_title_text": body_text,
                    "button_list": buttons,
                },
            }

        if message.project_tag:
            body_text = f"[{message.project_tag}]\n\n{body_text}" if body_text else f"[{message.project_tag}]"

        return {
            "msgtype": "markdown",
            "markdown": {"content": body_text},
        }

    def on_message(
        self, callback: Callable[[InboundMessage], Awaitable[None]]
    ) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return bool(self._bot_id and self._secret)

    def _is_user_allowed(self, user_id: str) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    async def _on_text(self, frame: dict[str, Any]) -> None:
        try:
            body = frame.get("body", {})
            sender = body.get("from", {})
            user_id = sender.get("user_id", "")
            chat_id = body.get("chat_id", user_id)
            msg_id = body.get("msg_id")

            text = body.get("text", {}).get("content", "")
            if not text:
                items = body.get("mixed", {}).get("items", [])
                text_parts = [
                    it.get("text", {}).get("content", "")
                    for it in items
                    if it.get("type") == "text"
                ]
                text = "\n".join(t for t in text_parts if t)

            logger.info("[WeCom] recv from={} chat={} text={!r}",
                        user_id, chat_id, text[:200])

            if not self._is_user_allowed(user_id):
                logger.warning("[WeCom] user {} not in allowed list, ignored", user_id)
                return

            if self._callback and text:
                msg = InboundMessage(
                    sender_id=user_id,
                    content=text,
                    chat_id=chat_id,
                    message_id=msg_id,
                    raw=frame,
                )
                await self._callback(msg)
        except Exception:
            logger.exception("[WeCom] error handling text message")

    async def _on_card_event(self, frame: dict[str, Any]) -> None:
        try:
            body = frame.get("body", {})
            event_key = body.get("event_key", "")
            sender = body.get("from", {})
            user_id = sender.get("user_id", "")
            chat_id = body.get("chat_id", user_id)

            logger.info("[WeCom] card event from={} chat={} key={!r}",
                        user_id, chat_id, event_key)

            if not event_key or not self._is_user_allowed(user_id):
                return

            if self._callback:
                msg = InboundMessage(
                    sender_id=user_id,
                    content=event_key,
                    chat_id=chat_id,
                    raw=frame,
                )
                await self._callback(msg)
        except Exception:
            logger.exception("[WeCom] error handling card event")
