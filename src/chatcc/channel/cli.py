from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable

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


class CliChannel(MessageChannel):
    def __init__(self):
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._running = False
        self._read_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        self._running = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

    async def send(self, message: OutboundMessage) -> None:
        if isinstance(message.content, RichMessage):
            text = self.render(message.content)
        else:
            text = str(message.content)
        print(text, flush=True)

    def render(self, message: RichMessage) -> str:
        parts: list[str] = []
        if message.project_tag:
            parts.append(f"[{message.project_tag}]")
        for element in message.elements:
            match element:
                case TextElement(content=content):
                    parts.append(content)
                case CodeElement(code=code):
                    parts.append(f"  $ {code}")
                case ActionGroup(buttons=buttons):
                    hints = " | ".join(f"{b.command} {b.label}" for b in buttons)
                    parts.append(f"  → {hints}")
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    parts.append(f"  ⏳ {tag}{desc}")
                case DividerElement():
                    parts.append("  " + "─" * 40)
        return "\n".join(parts)

    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return True

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                line = line.strip()
                if not line:
                    continue
                if self._callback:
                    msg = InboundMessage(sender_id="cli-user", content=line, chat_id="cli")
                    await self._callback(msg)
            except (EOFError, KeyboardInterrupt):
                break
