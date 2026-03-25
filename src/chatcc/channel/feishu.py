from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

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

logger = logging.getLogger("chatcc.channel.feishu")


class FeishuChannel(MessageChannel):

    @staticmethod
    def interactive_setup(ui: SetupUI) -> dict[str, Any]:
        ui.echo("=== 飞书应用认证 ===")
        app_id = ui.prompt("请输入 App ID")
        app_secret = ui.prompt("请输入 App Secret", hide=True)

        if not app_id or not app_secret:
            raise ValueError("App ID 和 App Secret 不能为空")

        allowed = ui.prompt("允许的用户 Open ID (逗号分隔, 留空允许所有)", default="")
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
            .build()
        )

        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, self._ws_client.start)
        logger.info("Feishu channel started (WebSocket)")

    async def stop(self) -> None:
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
                        actions.append(
                            {
                                "tag": "button",
                                "text": {"content": b.label, "tag": "lark_md"},
                                "type": "primary"
                                if "/y" in b.command
                                else "danger",
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
            "msg_type": "text",
            "content": {"text": content},
        }

    def _is_user_allowed(self, open_id: str) -> bool:
        if not self._allowed_users:
            return True
        return open_id in self._allowed_users

    def _on_message_event(self, data: Any) -> None:
        try:
            event = data.event
            sender = event.sender.sender_id.open_id
            message = event.message

            if not self._is_user_allowed(sender):
                return

            content_json = json.loads(message.content)
            text = content_json.get("text", "")

            if self._callback:
                msg = InboundMessage(
                    sender_id=sender,
                    content=text,
                    chat_id=message.chat_id,
                    raw=data,
                )
                loop = asyncio.get_event_loop()
                loop.create_task(self._callback(msg))

        except Exception:
            logger.exception("Error handling Feishu message event")

    def _on_card_action(self, data: Any) -> Any:
        try:
            action = data.event.action
            value = action.value
            command = value.get("command", "")
            open_id = data.event.operator.open_id
            chat_id = data.event.context.open_chat_id

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

        except Exception:
            logger.exception("Error handling Feishu card action")
        return None
