"""iLink Bot API: types, errors, HTTP protocol, and QR-code authentication.

This module consolidates the entire iLink protocol layer into a single file,
covering type definitions, error hierarchy, low-level HTTP calls, and the
QR-code login + credential persistence flow.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote
from uuid import uuid4

import aiohttp

# ── Types ────────────────────────────────────────────────────────────────


class MessageType(IntEnum):
    USER = 1
    BOT = 2


class MessageState(IntEnum):
    NEW = 0
    GENERATING = 1
    FINISH = 2


class MessageItemType(IntEnum):
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


class MediaType(IntEnum):
    IMAGE = 1
    VIDEO = 2
    FILE = 3
    VOICE = 4


ContentType = Literal["text", "image", "voice", "file", "video"]


@dataclass
class CDNMedia:
    encrypt_query_param: str
    aes_key: str
    encrypt_type: int | None = None


@dataclass
class ImageContent:
    media: CDNMedia | None = None
    thumb_media: CDNMedia | None = None
    aes_key: str | None = None
    url: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class VoiceContent:
    media: CDNMedia | None = None
    text: str | None = None
    duration_ms: int | None = None
    encode_type: int | None = None


@dataclass
class FileContent:
    media: CDNMedia | None = None
    file_name: str | None = None
    md5: str | None = None
    size: int | None = None


@dataclass
class VideoContent:
    media: CDNMedia | None = None
    thumb_media: CDNMedia | None = None
    duration_ms: int | None = None


@dataclass
class QuotedMessage:
    title: str | None = None
    text: str | None = None


@dataclass
class Credentials:
    token: str
    base_url: str
    account_id: str
    user_id: str
    saved_at: str | None = None


@dataclass
class IncomingMessage:
    """A parsed user message from the iLink long-poll."""
    user_id: str
    text: str
    type: ContentType
    timestamp: datetime
    images: list[ImageContent] = field(default_factory=list)
    voices: list[VoiceContent] = field(default_factory=list)
    files: list[FileContent] = field(default_factory=list)
    videos: list[VideoContent] = field(default_factory=list)
    quoted_message: QuotedMessage | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    _context_token: str = ""


# ── Errors ───────────────────────────────────────────────────────────────


class ILinkError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.code = code


class ApiError(ILinkError):
    def __init__(
        self,
        message: str,
        *,
        http_status: int = 0,
        errcode: int = 0,
        payload: object = None,
    ) -> None:
        super().__init__(message, "API_ERROR")
        self.http_status = http_status
        self.errcode = errcode
        self.payload = payload

    @property
    def is_session_expired(self) -> bool:
        return self.errcode == -14


class AuthError(ILinkError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "AUTH_ERROR")


# ── Protocol (HTTP) ─────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://ilinkai.weixin.qq.com"
CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
CHANNEL_VERSION = "2.0.0"


def _random_wechat_uin() -> str:
    val = struct.unpack(">I", os.urandom(4))[0]
    return base64.b64encode(str(val).encode("utf-8")).decode("ascii")


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": _random_wechat_uin(),
    }


def _base_info() -> dict[str, str]:
    return {"channel_version": CHANNEL_VERSION}


async def _parse_response(resp: aiohttp.ClientResponse, label: str) -> dict[str, Any]:
    text = await resp.text()
    payload: dict[str, Any] = json.loads(text) if text else {}

    if resp.status >= 400:
        msg = payload.get("errmsg") or f"{label} failed with HTTP {resp.status}"
        raise ApiError(msg, http_status=resp.status, errcode=payload.get("errcode", 0), payload=payload)

    ret = payload.get("ret")
    if isinstance(ret, int) and ret != 0:
        code = payload.get("errcode", ret)
        msg = payload.get("errmsg") or f"{label} failed (ret={ret})"
        raise ApiError(msg, http_status=resp.status, errcode=code, payload=payload)

    return payload


class ILinkApi:
    """Low-level iLink API client. Each method maps 1:1 to an endpoint."""

    def __init__(self) -> None:
        self._timeout = aiohttp.ClientTimeout(total=45)

    async def get_qr_code(self, base_url: str) -> dict[str, Any]:
        url = f"{base_url}/ilink/bot/get_bot_qrcode?bot_type=3"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await _parse_response(resp, "get_bot_qrcode")

    async def poll_qr_status(self, base_url: str, qrcode: str) -> dict[str, Any]:
        url = f"{base_url}/ilink/bot/get_qrcode_status?qrcode={quote(qrcode, safe='')}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={"iLink-App-ClientVersion": "1"}) as resp:
                return await _parse_response(resp, "get_qrcode_status")

    async def get_updates(self, base_url: str, token: str, cursor: str) -> dict[str, Any]:
        body = {"get_updates_buf": cursor, "base_info": _base_info()}
        return await self._post(base_url, "/ilink/bot/getupdates", token, body, 45)

    async def send_message(self, base_url: str, token: str, msg: dict[str, Any]) -> dict[str, Any]:
        body = {"msg": msg, "base_info": _base_info()}
        return await self._post(base_url, "/ilink/bot/sendmessage", token, body)

    async def get_config(
        self, base_url: str, token: str, user_id: str, context_token: str,
    ) -> dict[str, Any]:
        body = {"ilink_user_id": user_id, "context_token": context_token, "base_info": _base_info()}
        return await self._post(base_url, "/ilink/bot/getconfig", token, body)

    async def send_typing(
        self, base_url: str, token: str, user_id: str, ticket: str, status: int,
    ) -> dict[str, Any]:
        body = {
            "ilink_user_id": user_id,
            "typing_ticket": ticket,
            "status": status,
            "base_info": _base_info(),
        }
        return await self._post(base_url, "/ilink/bot/sendtyping", token, body)

    async def get_upload_url(self, base_url: str, token: str, params: dict[str, Any]) -> dict[str, Any]:
        body = {**params, "base_info": _base_info()}
        return await self._post(base_url, "/ilink/bot/getuploadurl", token, body)

    def build_text_message(self, user_id: str, context_token: str, text: str) -> dict[str, Any]:
        return {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": str(uuid4()),
            "message_type": MessageType.BOT,
            "message_state": MessageState.FINISH,
            "context_token": context_token,
            "item_list": [{"type": MessageItemType.TEXT, "text_item": {"text": text}}],
        }

    def build_media_message(
        self, user_id: str, context_token: str, item_list: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": str(uuid4()),
            "message_type": MessageType.BOT,
            "message_state": MessageState.FINISH,
            "context_token": context_token,
            "item_list": item_list,
        }

    async def _post(
        self, base_url: str, endpoint: str, token: str, body: dict[str, Any], timeout_secs: int = 15,
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=timeout_secs)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=_auth_headers(token), json=body) as resp:
                return await _parse_response(resp, endpoint)


# ── Auth (QR login + credential persistence) ────────────────────────────

DEFAULT_CRED_DIR = Path.home() / ".wechatbot"
DEFAULT_CRED_PATH = DEFAULT_CRED_DIR / "credentials.json"
QR_POLL_INTERVAL = 2.0


async def load_credentials(path: Path | None = None) -> Credentials | None:
    target = path or DEFAULT_CRED_PATH
    try:
        data = json.loads(target.read_text("utf-8"))
        return Credentials(
            token=data["token"],
            base_url=data.get("base_url") or data.get("baseUrl", ""),
            account_id=data.get("account_id") or data.get("accountId", ""),
            user_id=data.get("user_id") or data.get("userId", ""),
            saved_at=data.get("saved_at") or data.get("savedAt"),
        )
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, KeyError) as e:
        raise AuthError(f"Invalid credentials file: {e}") from e


async def save_credentials(creds: Credentials, path: Path | None = None) -> None:
    target = path or DEFAULT_CRED_PATH
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "token": creds.token,
        "baseUrl": creds.base_url,
        "accountId": creds.account_id,
        "userId": creds.user_id,
        "savedAt": creds.saved_at,
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)


async def clear_credentials(path: Path | None = None) -> None:
    target = path or DEFAULT_CRED_PATH
    target.unlink(missing_ok=True)


async def login(
    api: ILinkApi,
    *,
    base_url: str = DEFAULT_BASE_URL,
    cred_path: Path | None = None,
    force: bool = False,
    on_qr_url: Callable[[str], None] | None = None,
    on_scanned: Callable[[], None] | None = None,
    on_expired: Callable[[], None] | None = None,
) -> Credentials:
    """QR code login. Returns stored credentials if available and force=False."""
    if not force:
        stored = await load_credentials(cred_path)
        if stored:
            return stored

    while True:
        qr = await api.get_qr_code(base_url)
        qr_url = qr["qrcode_img_content"]

        if on_qr_url:
            on_qr_url(qr_url)
        else:
            print(f"[wechatbot] Scan this URL in WeChat: {qr_url}", file=sys.stderr)

        last_status = ""
        while True:
            status = await api.poll_qr_status(base_url, qr["qrcode"])
            current = status["status"]

            if current != last_status:
                last_status = current
                if current == "scaned":
                    if on_scanned:
                        on_scanned()
                    else:
                        print("[wechatbot] QR scanned — confirm in WeChat", file=sys.stderr)
                elif current == "expired":
                    if on_expired:
                        on_expired()
                    else:
                        print("[wechatbot] QR expired — requesting new one", file=sys.stderr)
                elif current == "confirmed":
                    print("[wechatbot] Login confirmed", file=sys.stderr)

            if current == "confirmed":
                token = status.get("bot_token")
                bot_id = status.get("ilink_bot_id")
                user_id = status.get("ilink_user_id")
                if not token or not bot_id or not user_id:
                    raise AuthError("Login confirmed but missing credentials")

                creds = Credentials(
                    token=token,
                    base_url=status.get("baseurl") or base_url,
                    account_id=bot_id,
                    user_id=user_id,
                    saved_at=datetime.now(timezone.utc).isoformat(),
                )
                await save_credentials(creds, cred_path)
                return creds

            if current == "expired":
                break

            await asyncio.sleep(QR_POLL_INTERVAL)


# ── Message parsing helpers ──────────────────────────────────────────────


def parse_cdn_media(data: dict[str, Any] | None) -> CDNMedia | None:
    if not data:
        return None
    return CDNMedia(
        encrypt_query_param=data.get("encrypt_query_param", ""),
        aes_key=data.get("aes_key", ""),
        encrypt_type=data.get("encrypt_type"),
    )


def detect_type(items: list[dict[str, Any]]) -> ContentType:
    if not items:
        return "text"
    t = items[0].get("type")
    return {
        MessageItemType.IMAGE: "image",
        MessageItemType.VOICE: "voice",
        MessageItemType.FILE: "file",
        MessageItemType.VIDEO: "video",
    }.get(t, "text")


def extract_text(items: list[dict[str, Any]]) -> str:
    parts = []
    for item in items:
        t = item.get("type")
        if t == MessageItemType.TEXT:
            parts.append(item.get("text_item", {}).get("text", ""))
        elif t == MessageItemType.IMAGE:
            parts.append(item.get("image_item", {}).get("url", "[image]"))
        elif t == MessageItemType.VOICE:
            parts.append(item.get("voice_item", {}).get("text", "[voice]"))
        elif t == MessageItemType.FILE:
            parts.append(item.get("file_item", {}).get("file_name", "[file]"))
        elif t == MessageItemType.VIDEO:
            parts.append("[video]")
    return "\n".join(p for p in parts if p)
