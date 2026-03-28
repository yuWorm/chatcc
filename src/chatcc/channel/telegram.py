from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from telegram import (
    Bot,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction
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

if TYPE_CHECKING:
    from chatcc.command.spec import CommandSpec
    from chatcc.setup.ui import SetupUI

from loguru import logger


class TelegramChannel(MessageChannel):
    MAX_MESSAGE_LENGTH = 4096

    @staticmethod
    def interactive_setup(
        ui: SetupUI,
        *,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import questionary as q

        ex = existing or {}
        has_existing = existing is not None

        q.print("=== Telegram Bot 认证 ===", style="bold fg:cyan")

        new_token = ui.prompt_secret("Bot Token (从 @BotFather 获取)", has_existing=has_existing)
        token = new_token if new_token is not None else ex.get("token", "")

        if not token or ":" not in token:
            raise ValueError("Token 格式无效 (应为 数字:字母串)")

        default_allowed = ",".join(str(u) for u in ex.get("allowed_users", []))
        allowed = ui.prompt(
            "允许的用户 ID 或用户名 (逗号分隔, 用户名不加@, 留空允许所有)",
            default=default_allowed,
        )
        allowed_list = [u.strip() for u in allowed.split(",") if u.strip()]

        return {
            "token": token,
            "allowed_users": allowed_list,
        }

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

    async def send_typing(self, chat_id: str, message_id: str | None = None) -> None:
        if self._bot:
            try:
                await self._bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                logger.debug("send_typing timed out for chat_id={}", chat_id)

    async def register_commands(self, commands: list[CommandSpec]) -> None:
        if not self._bot:
            return
        bot_commands = [
            BotCommand(command=spec.name, description=spec.description)
            for spec in commands
        ]
        try:
            await self._bot.set_my_commands(bot_commands)
            logger.info("Telegram 菜单已注册 {} 条命令", len(bot_commands))
        except Exception:
            logger.exception("注册 Telegram 命令菜单失败")

    def _is_user_allowed(self, user_id: str, username: str | None = None) -> bool:
        if not self._allowed_users:
            return True
        if str(user_id) in self._allowed_users:
            return True
        if username and username.lower() in (u.lower() for u in self._allowed_users):
            return True
        return False

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
        user = update.message.from_user
        user_id = str(user.id)
        username = user.username
        logger.info("收到文本消息: user={} (@{}), chat={}, text={}",
                     user_id, username, update.message.chat_id, update.message.text)
        if not self._is_user_allowed(user_id, username):
            logger.warning("用户 {} (@{}) 不在允许列表中，已忽略", user_id, username)
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
        user = update.message.from_user
        user_id = str(user.id)
        username = user.username
        logger.info("收到命令消息: user={} (@{}), chat={}, command={}",
                     user_id, username, update.message.chat_id, update.message.text)
        if not self._is_user_allowed(user_id, username):
            logger.warning("用户 {} (@{}) 不在允许列表中，已忽略", user_id, username)
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
        username = query.from_user.username
        logger.info("收到回调按钮: user={} (@{}), chat={}, data={}",
                     user_id, username, query.message.chat_id, query.data)
        if not self._is_user_allowed(user_id, username):
            logger.warning("用户 {} (@{}) 不在允许列表中，已忽略", user_id, username)
            return

        if self._callback:
            msg = InboundMessage(
                sender_id=user_id,
                content=query.data,
                chat_id=str(query.message.chat_id),
                raw=update,
            )
            await self._callback(msg)
