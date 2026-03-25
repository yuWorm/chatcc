from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    MessageHandler,
    filters,
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

logger = logging.getLogger("chatcc.channel.telegram")


class TelegramChannel(MessageChannel):
    MAX_MESSAGE_LENGTH = 4096

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._token: str = config.get("token", "")
        self._allowed_users: list[str] = [
            str(u) for u in config.get("allowed_users", [])
        ]
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._app: Application | None = None
        self._bot: Bot | None = None

    async def start(self) -> None:
        if not self._token:
            raise RuntimeError("Telegram token not configured")

        self._app = ApplicationBuilder().token(self._token).build()
        self._bot = self._app.bot

        self._app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, self._handle_text_message
            )
        )
        self._app.add_handler(
            MessageHandler(filters.COMMAND, self._handle_command_message)
        )
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram channel started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram channel stopped")

    async def send(self, message: OutboundMessage) -> None:
        if not self._bot:
            raise RuntimeError("Telegram bot not started")

        if isinstance(message.content, RichMessage):
            text, keyboard = self.render(message.content)
            chunks = self._split_text(text, self.MAX_MESSAGE_LENGTH)
            for i, chunk in enumerate(chunks):
                is_last = i == len(chunks) - 1
                await self._bot.send_message(
                    chat_id=message.chat_id,
                    text=chunk,
                    reply_markup=keyboard if is_last else None,
                    parse_mode="Markdown",
                    reply_to_message_id=message.reply_to,
                )
        else:
            for chunk in self._split_text(str(message.content), self.MAX_MESSAGE_LENGTH):
                await self._bot.send_message(
                    chat_id=message.chat_id,
                    text=chunk,
                    reply_to_message_id=message.reply_to,
                )

    def render(
        self, message: RichMessage
    ) -> tuple[str, InlineKeyboardMarkup | None]:
        text_parts: list[str] = []
        keyboard_rows: list[list[InlineKeyboardButton]] = []

        if message.project_tag:
            text_parts.append(f"[{message.project_tag}]")

        for element in message.elements:
            match element:
                case TextElement(content=content):
                    text_parts.append(content)
                case CodeElement(code=code, language=lang):
                    text_parts.append(f"```{lang}\n{code}\n```")
                case ActionGroup(buttons=buttons):
                    row = [
                        InlineKeyboardButton(b.label, callback_data=b.command)
                        for b in buttons
                    ]
                    keyboard_rows.append(row)
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    text_parts.append(f"⏳ {tag}{desc}")
                case DividerElement():
                    text_parts.append("───────────")

        text = "\n\n".join(text_parts)
        keyboard = InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None
        return text, keyboard

    def on_message(
        self, callback: Callable[[InboundMessage], Awaitable[None]]
    ) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return bool(self._token)

    def _is_user_allowed(self, user_id: str) -> bool:
        if not self._allowed_users:
            return True
        return str(user_id) in self._allowed_users

    @staticmethod
    def _split_text(text: str, max_len: int) -> list[str]:
        if len(text) <= max_len:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def _handle_text_message(self, update: Update, context: Any) -> None:
        if not update.message or not update.message.text:
            return
        user_id = str(update.message.from_user.id)
        if not self._is_user_allowed(user_id):
            return
        if self._callback:
            msg = InboundMessage(
                sender_id=user_id,
                content=update.message.text,
                chat_id=str(update.message.chat_id),
                raw=update,
            )
            await self._callback(msg)

    async def _handle_command_message(self, update: Update, context: Any) -> None:
        if not update.message or not update.message.text:
            return
        user_id = str(update.message.from_user.id)
        if not self._is_user_allowed(user_id):
            return
        if self._callback:
            msg = InboundMessage(
                sender_id=user_id,
                content=update.message.text,
                chat_id=str(update.message.chat_id),
                raw=update,
            )
            await self._callback(msg)

    async def _handle_callback(self, update: Update, context: Any) -> None:
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()

        user_id = str(query.from_user.id)
        if not self._is_user_allowed(user_id):
            return

        if self._callback:
            msg = InboundMessage(
                sender_id=user_id,
                content=query.data,
                chat_id=str(query.message.chat_id),
                raw=update,
            )
            await self._callback(msg)
