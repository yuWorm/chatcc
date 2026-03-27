from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import lark_oapi as lark
import lark_oapi.ws.client as _lark_ws_mod
from lark_oapi.ws.exception import ClientException as LarkClientException
from lark_oapi.api.im.v1 import (
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    CreateMessageRequest,
    CreateMessageRequestBody,
)
from lark_oapi.api.im.v1.model.emoji import Emoji

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

from loguru import logger


class FeishuChannel(MessageChannel):

    @staticmethod
    def interactive_setup(
        ui: SetupUI,
        *,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import questionary as q

        ex = existing or {}
        has_existing = existing is not None

        q.print("=== 飞书应用认证 ===", style="bold fg:cyan")
        app_id = ui.prompt("请输入 App ID", default=ex.get("app_id", ""))

        new_secret = ui.prompt_secret("请输入 App Secret", has_existing=has_existing)
        app_secret = new_secret if new_secret is not None else ex.get("app_secret", "")

        if not app_id or not app_secret:
            raise ValueError("App ID 和 App Secret 不能为空")

        default_allowed = ",".join(str(u) for u in ex.get("allowed_users", []))
        allowed = ui.prompt("允许的用户 Open ID (逗号分隔, 留空允许所有)", default=default_allowed)
        allowed_list = [u.strip() for u in allowed.split(",") if u.strip()]

        return {
            "app_id": app_id,
            "app_secret": app_secret,
            "allowed_users": allowed_list,
        }

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._app_id: str = config.get("app_id", "")
        self._app_secret: str = config.get("app_secret", "")
        self._allowed_users: list[str] = config.get("allowed_users", [])
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._api_client: lark.Client | None = None
        self._ws_client: lark.ws.Client | None = None

    async def start(self) -> None:
        if not self._app_id or not self._app_secret:
            raise RuntimeError("Feishu app_id/app_secret not configured")

        self._api_client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .build()
        )

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_event)
            .register_p2_card_action_trigger(self._on_card_action)
            .build()
        )

        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        _lark_ws_mod.loop = asyncio.get_running_loop()

        try:
            await self._ws_client._connect()
        except LarkClientException:
            raise
        except Exception as e:
            logger.error(f"Feishu WS connect failed: {e}")
            await self._ws_client._disconnect()
            if self._ws_client._auto_reconnect:
                asyncio.create_task(self._ws_client._reconnect())
            else:
                raise

        asyncio.create_task(self._ws_client._ping_loop())
        logger.info("Feishu channel started (WebSocket)")

    async def stop(self) -> None:
        if self._ws_client:
            await self._ws_client._disconnect()
        logger.info("Feishu channel stopped")

    async def send(self, message: OutboundMessage) -> None:
        if not self._api_client:
            raise RuntimeError("Feishu API client not initialized")

        payload = self._build_send_payload(message.chat_id, message.content)

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(payload["receive_id"])
                .msg_type(payload["msg_type"])
                .content(json.dumps(payload["content"], ensure_ascii=False))
                .build()
            )
            .build()
        )

        logger.info("[Feishu] send to={} type={}", payload["receive_id"], payload["msg_type"])
        response = await self._api_client.im.v1.message.acreate(request)
        if not response.success():
            logger.error(
                f"Failed to send message: {response.code} - {response.msg}"
            )

    def render(self, message: RichMessage) -> dict[str, Any]:
        elements: list[dict[str, Any]] = []

        for el in message.elements:
            match el:
                case TextElement(content=content):
                    elements.append(
                        {
                            "tag": "div",
                            "text": {"content": content, "tag": "lark_md"},
                        }
                    )
                case CodeElement(code=code, language=lang):
                    md_code = f"```{lang}\n{code}\n```"
                    elements.append(
                        {
                            "tag": "div",
                            "text": {"content": md_code, "tag": "lark_md"},
                        }
                    )
                case ActionGroup(buttons=buttons):
                    actions = []
                    for b in buttons:
                        if b.style:
                            btn_type = b.style
                        elif "/y" in b.command:
                            btn_type = "primary"
                        else:
                            btn_type = "danger"
                        actions.append(
                            {
                                "tag": "button",
                                "text": {"content": b.label, "tag": "lark_md"},
                                "type": btn_type,
                                "value": {"command": b.command},
                            }
                        )
                    elements.append({"tag": "action", "actions": actions})
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    elements.append(
                        {
                            "tag": "note",
                            "elements": [
                                {
                                    "tag": "plain_text",
                                    "content": f"⏳ {tag}{desc}",
                                }
                            ],
                        }
                    )
                case DividerElement():
                    elements.append({"tag": "hr"})

        if message.project_tag:
            header = {
                "title": {
                    "content": f"[{message.project_tag}] ChatCC",
                    "tag": "plain_text",
                }
            }
        else:
            header = {
                "title": {"content": "ChatCC", "tag": "plain_text"}
            }

        return {
            "msg_type": "interactive",
            "card": {"header": header, "elements": elements},
        }

    async def send_typing(self, chat_id: str, message_id: str | None = None) -> None:
        if not self._api_client or not message_id:
            return
        try:
            request = (
                CreateMessageReactionRequest.builder()
                .message_id(message_id)
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type("DONE").build())
                    .build()
                )
                .build()
            )
            response = await self._api_client.im.v1.message_reaction.acreate(request)
            if not response.success():
                logger.warning(
                    "[Feishu] add reaction failed: {} - {}", response.code, response.msg
                )
        except Exception:
            logger.debug("[Feishu] add reaction failed", exc_info=True)

    def on_message(
        self, callback: Callable[[InboundMessage], Awaitable[None]]
    ) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return bool(self._app_id and self._app_secret)

    def _build_send_payload(
        self, chat_id: str, content: str | RichMessage
    ) -> dict[str, Any]:
        if isinstance(content, RichMessage):
            card_data = self.render(content)
            return {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": card_data["card"],
            }
        return {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": {
                "elements": [{"tag": "markdown", "content": content}],
            },
        }

    def _is_user_allowed(self, open_id: str) -> bool:
        if not self._allowed_users:
            return True
        return open_id in self._allowed_users

    @staticmethod
    def _extract_text(message: Any) -> str:
        """Extract readable text from any Feishu message type."""
        content = json.loads(message.content)
        msg_type = getattr(message, "message_type", "text")

        if msg_type == "text":
            return content.get("text", "")

        if msg_type == "interactive":
            parts: list[str] = []
            header = content.get("header") or {}
            title = header.get("title") or {}
            if title.get("content"):
                parts.append(title["content"])
            for el in content.get("elements", []):
                tag = el.get("tag", "")
                if tag == "markdown":
                    parts.append(el.get("content", ""))
                elif tag == "div":
                    t = el.get("text") or {}
                    parts.append(t.get("content", ""))
                elif tag in ("note", "action"):
                    for sub in el.get("elements", []):
                        parts.append(sub.get("content", ""))
            return "\n".join(p for p in parts if p)

        if msg_type == "post":
            parts = []

            def _extract_post_body(body: dict) -> None:
                if body.get("title"):
                    parts.append(body["title"])
                for para in body.get("content", []):
                    for seg in para:
                        if seg.get("text"):
                            parts.append(seg["text"])

            if "content" in content and isinstance(content["content"], list):
                _extract_post_body(content)
            else:
                for lang_body in content.values():
                    if isinstance(lang_body, dict):
                        _extract_post_body(lang_body)

            return "\n".join(parts)

        return json.dumps(content, ensure_ascii=False)

    def _on_message_event(self, data: Any) -> None:
        try:
            event = data.event
            sender = event.sender.sender_id.open_id
            message = event.message

            if not self._is_user_allowed(sender):
                return

            text = self._extract_text(message)
            logger.info("[Feishu] recv type={} from={} chat={} text={!r}",
                        getattr(message, "message_type", "?"), sender, message.chat_id, text)

            if self._callback:
                msg = InboundMessage(
                    sender_id=sender,
                    content=text,
                    chat_id=message.chat_id,
                    message_id=message.message_id,
                    raw=data,
                )
                loop = asyncio.get_event_loop()
                loop.create_task(self._callback(msg))

        except Exception:
            logger.exception("Error handling Feishu message event")

    def _on_card_action(self, data: Any) -> Any:
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTriggerResponse,
        )

        try:
            action = data.event.action
            value = action.value
            command = value.get("command", "")
            open_id = data.event.operator.open_id
            chat_id = data.event.context.open_chat_id
            logger.info("[Feishu] card action from={} chat={} cmd={!r}", open_id, chat_id, command)

            if not command or not self._is_user_allowed(open_id):
                return None

            if self._callback:
                msg = InboundMessage(
                    sender_id=open_id,
                    content=command,
                    chat_id=chat_id,
                    raw=data,
                )
                loop = asyncio.get_event_loop()
                loop.create_task(self._callback(msg))

            label = self._action_label(command)
            return P2CardActionTriggerResponse({
                "toast": {"type": "success", "content": label},
                "card": {
                    "type": "raw",
                    "data": {
                        "header": {
                            "title": {"content": "ChatCC", "tag": "plain_text"},
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "text": {"content": label, "tag": "lark_md"},
                            }
                        ],
                    },
                },
            })

        except Exception:
            logger.exception("Error handling Feishu card action")
        return None

    @staticmethod
    def _action_label(command: str) -> str:
        _RESOLVE_LABELS = {
            "queue": "📋 已选择: 排队等待",
            "interrupt": "⚡ 已选择: 打断执行",
            "cancel": "❌ 已选择: 取消",
            "approve": "✅ 已确认",
            "deny": "❌ 已取消",
        }
        if command.startswith("/y"):
            return "✅ 已确认"
        if command.startswith("/n"):
            return "❌ 已拒绝"
        if command.startswith("/resolve"):
            parts = command.split()
            if len(parts) >= 3:
                return _RESOLVE_LABELS.get(parts[2], f"已选择: {parts[2]}")
        return "已处理"
