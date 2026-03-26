from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class InboundMessage:
    sender_id: str
    content: str
    chat_id: str
    message_id: str | None = None
    media: list[str] | None = None
    raw: Any = None


@dataclass
class TextElement:
    content: str


@dataclass
class CodeElement:
    code: str
    language: str = ""


@dataclass
class ActionButton:
    label: str
    command: str


@dataclass
class ActionGroup:
    buttons: list[ActionButton]


@dataclass
class ProgressElement:
    description: str
    project: str = ""


@dataclass
class DividerElement:
    pass


MessageElement = TextElement | CodeElement | ActionGroup | ProgressElement | DividerElement


@dataclass
class RichMessage:
    elements: list[MessageElement]
    reply_to: str | None = None
    project_tag: str | None = None


@dataclass
class OutboundMessage:
    chat_id: str
    content: str | RichMessage
    reply_to: str | None = None
