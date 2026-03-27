"""WeChat iLink Bot channel — implements MessageChannel for chatcc."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import aiohttp
from loguru import logger

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

from .crypto import (
    CryptoError,
    decode_aes_key,
    decrypt_aes_ecb,
    encode_aes_key_base64,
    encode_aes_key_hex,
    encrypt_aes_ecb,
    generate_aes_key,
)
from .ilink import (
    CDN_BASE_URL,
    DEFAULT_BASE_URL,
    DEFAULT_CRED_PATH,
    ApiError,
    CDNMedia,
    Credentials,
    FileContent,
    ILinkApi,
    ImageContent,
    MediaType,
    MessageItemType,
    MessageType,
    QuotedMessage,
    VideoContent,
    VoiceContent,
    clear_credentials,
    detect_type,
    extract_text,
    load_credentials,
    login,
    parse_cdn_media,
)
from .ilink import (
    IncomingMessage as ILinkMessage,
)

if TYPE_CHECKING:
    from chatcc.setup.ui import SetupUI

MAX_TEXT_CHUNK = 2000


class WeChatChannel(MessageChannel):
    @staticmethod
    def interactive_setup(
        ui: SetupUI,
        *,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import asyncio

        ex = existing or {}

        ui.echo("=== 微信 iLink Bot 认证 ===")
        cred_path_str = ui.prompt(
            "凭证文件路径 (留空使用默认 ~/.wechatbot/credentials.json)",
            default=ex.get("cred_path", ""),
        )
        cred_path = Path(cred_path_str) if cred_path_str else None

        default_allowed = ",".join(str(u) for u in ex.get("allowed_users", []))
        allowed = ui.prompt(
            "允许的用户 ID (逗号分隔, 留空允许所有)", default=default_allowed
        )
        allowed_list = [u.strip() for u in allowed.split(",") if u.strip()]

        stored = asyncio.run(load_credentials(cred_path))
        if stored:
            reauth = ui.confirm(
                f"已有保存的凭证 (user_id: {stored.user_id})，是否重新扫码?",
                default=False,
            )
            if not reauth:
                ui.echo(f"使用已保存的凭证 ✓")
                return {"cred_path": cred_path_str or "", "allowed_users": allowed_list}

        ui.echo("正在获取二维码...")
        try:
            creds = asyncio.run(_qr_login_sync(ui, cred_path))
            ui.echo(f"✅ 登录成功 (user_id: {creds.user_id})")
        except Exception as e:
            raise ValueError(f"登录失败: {e}") from e

        return {"cred_path": cred_path_str or "", "allowed_users": allowed_list}

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._cred_path: Path | None = (
            Path(config["cred_path"]) if config.get("cred_path") else None
        )
        self._allowed_users: list[str] = [
            str(u) for u in config.get("allowed_users", [])
        ]
        self._base_url: str = config.get("base_url", DEFAULT_BASE_URL)

        self._api = ILinkApi()
        self._credentials: Credentials | None = None
        self._context_tokens: dict[str, str] = {}
        self._cursor = ""
        self._stopped = False
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._poll_task: asyncio.Task[None] | None = None

    # ── MessageChannel interface ─────────────────────────────────────

    async def start(self) -> None:
        creds = await login(
            self._api,
            base_url=self._base_url,
            cred_path=self._cred_path,
            force=False,
        )
        self._credentials = creds
        self._base_url = creds.base_url
        logger.info("WeChat channel logged in as {}", creds.user_id)

        self._stopped = False
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("WeChat channel started (long-poll)")

    async def stop(self) -> None:
        self._stopped = True
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("WeChat channel stopped")

    async def send(self, message: OutboundMessage) -> None:
        creds = self._require_creds()
        ct = self._context_tokens.get(message.chat_id)
        if not ct:
            logger.warning(
                "No context_token for chat_id={}, cannot send", message.chat_id
            )
            return

        if isinstance(message.content, RichMessage):
            text = self.render(message.content)
        else:
            text = str(message.content)

        chunks = _chunk_text(text, MAX_TEXT_CHUNK)
        logger.info(
            "[WeChat] send to={} len={} chunks={}",
            message.chat_id,
            len(text),
            len(chunks),
        )

        for chunk in chunks:
            msg = self._api.build_text_message(message.chat_id, ct, chunk)
            await self._api.send_message(creds.base_url, creds.token, msg)

    def render(self, message: RichMessage) -> str:
        parts: list[str] = []
        if message.project_tag:
            parts.append(f"[{message.project_tag}]")

        for el in message.elements:
            match el:
                case TextElement(content=content):
                    parts.append(content)
                case CodeElement(code=code, language=lang):
                    parts.append(f"```{lang}\n{code}\n```")
                case ActionGroup(buttons=buttons):
                    parts.append(
                        " | ".join(f"[{b.label}] {b.command}" for b in buttons)
                    )
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    parts.append(f"⏳ {tag}{desc}")
                case DividerElement():
                    parts.append("───────────")

        return "\n\n".join(parts)

    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        if self._credentials is not None:
            return True
        target = self._cred_path or DEFAULT_CRED_PATH
        return target.exists()

    async def send_typing(self, chat_id: str, message_id: str | None = None) -> None:
        ct = self._context_tokens.get(chat_id)
        if not ct or not self._credentials:
            return
        try:
            creds = self._credentials
            config = await self._api.get_config(
                creds.base_url, creds.token, chat_id, ct
            )
            ticket = config.get("typing_ticket")
            if ticket:
                await self._api.send_typing(
                    creds.base_url, creds.token, chat_id, ticket, 1
                )
        except Exception:
            logger.debug("send_typing failed for chat_id={}", chat_id)

    # ── Long-poll loop ───────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        retry_delay = 1.0

        while not self._stopped:
            try:
                creds = self._require_creds()
                updates = await self._api.get_updates(
                    creds.base_url, creds.token, self._cursor
                )

                buf = updates.get("get_updates_buf")
                if buf:
                    self._cursor = buf
                retry_delay = 1.0

                for raw in updates.get("msgs", []):
                    self._remember_context(raw)
                    msg = self._parse_message(raw)
                    if msg:
                        await self._dispatch(msg)

            except ApiError as e:
                if e.is_session_expired:
                    logger.warning("WeChat session expired — re-login")
                    await clear_credentials(self._cred_path)
                    self._context_tokens.clear()
                    self._cursor = ""
                    try:
                        creds = await login(
                            self._api,
                            base_url=self._base_url,
                            cred_path=self._cred_path,
                            force=True,
                        )
                        self._credentials = creds
                        self._base_url = creds.base_url
                        retry_delay = 1.0
                        continue
                    except Exception:
                        logger.exception("Re-login failed")
                else:
                    logger.error("iLink API error: {}", e)

                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 10.0)

            except asyncio.CancelledError:
                break

            except Exception:
                if self._stopped:
                    break
                logger.exception("WeChat poll error")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 10.0)

    # ── Inbound message parsing ──────────────────────────────────────

    def _remember_context(self, raw: dict[str, Any]) -> None:
        mt = raw.get("message_type")
        uid = (
            raw.get("from_user_id") if mt == MessageType.USER else raw.get("to_user_id")
        )
        ct = raw.get("context_token")
        if uid and ct:
            self._context_tokens[uid] = ct

    def _parse_message(self, raw: dict[str, Any]) -> ILinkMessage | None:
        if raw.get("message_type") != MessageType.USER:
            return None

        user_id = raw.get("from_user_id", "")
        if self._allowed_users and user_id not in self._allowed_users:
            logger.debug("[WeChat] ignored message from non-allowed user={}", user_id)
            return None

        items = raw.get("item_list", [])
        images, voices, files, videos = [], [], [], []
        quoted = None

        for item in items:
            t = item.get("type")
            if t == MessageItemType.IMAGE and item.get("image_item"):
                ii = item["image_item"]
                images.append(
                    ImageContent(
                        media=parse_cdn_media(ii.get("media")),
                        thumb_media=parse_cdn_media(ii.get("thumb_media")),
                        aes_key=ii.get("aeskey"),
                        url=ii.get("url"),
                        width=ii.get("thumb_width"),
                        height=ii.get("thumb_height"),
                    )
                )
            elif t == MessageItemType.VOICE and item.get("voice_item"):
                vi = item["voice_item"]
                voices.append(
                    VoiceContent(
                        media=parse_cdn_media(vi.get("media")),
                        text=vi.get("text"),
                        duration_ms=vi.get("playtime"),
                        encode_type=vi.get("encode_type"),
                    )
                )
            elif t == MessageItemType.FILE and item.get("file_item"):
                fi = item["file_item"]
                size = None
                if fi.get("len"):
                    try:
                        size = int(fi["len"])
                    except (ValueError, TypeError):
                        pass
                files.append(
                    FileContent(
                        media=parse_cdn_media(fi.get("media")),
                        file_name=fi.get("file_name"),
                        md5=fi.get("md5"),
                        size=size,
                    )
                )
            elif t == MessageItemType.VIDEO and item.get("video_item"):
                vi = item["video_item"]
                videos.append(
                    VideoContent(
                        media=parse_cdn_media(vi.get("media")),
                        thumb_media=parse_cdn_media(vi.get("thumb_media")),
                        duration_ms=vi.get("play_length"),
                    )
                )
            if item.get("ref_msg"):
                ref = item["ref_msg"]
                qt = ref.get("message_item", {}).get("text_item", {}).get("text")
                quoted = QuotedMessage(title=ref.get("title"), text=qt)

        return ILinkMessage(
            user_id=user_id,
            text=extract_text(items),
            type=detect_type(items),
            timestamp=datetime.fromtimestamp(
                raw.get("create_time_ms", 0) / 1000,
                tz=timezone.utc,
            ),
            images=images,
            voices=voices,
            files=files,
            videos=videos,
            quoted_message=quoted,
            raw=raw,
            _context_token=raw.get("context_token", ""),
        )

    async def _dispatch(self, ilink_msg: ILinkMessage) -> None:
        if not self._callback:
            return

        logger.info(
            "[WeChat] recv type={} from={} text={!r}",
            ilink_msg.type,
            ilink_msg.user_id,
            ilink_msg.text[:200] if ilink_msg.text else "",
        )

        media_urls = await self._collect_media(ilink_msg)

        inbound = InboundMessage(
            sender_id=ilink_msg.user_id,
            content=ilink_msg.text,
            chat_id=ilink_msg.user_id,
            media=media_urls or None,
            raw=ilink_msg,
        )

        if media_urls:
            logger.info("[WeChat] recv media count={} from={}", len(media_urls), ilink_msg.user_id)

        try:
            await self._callback(inbound)
        except Exception:
            logger.exception("Error in message callback for user={}", ilink_msg.user_id)

    async def _collect_media(self, msg: ILinkMessage) -> list[str]:
        """Extract media references from an iLink message.

        For images with a direct URL, uses the URL directly.
        For CDN-only media (files, videos, voice), downloads and decrypts,
        then saves to a temp file and returns the file path.
        """
        refs: list[str] = []

        for img in msg.images:
            if img.url:
                refs.append(img.url)
            elif img.media:
                path = await self._download_to_temp(
                    img.media, img.aes_key, suffix=".jpg"
                )
                if path:
                    refs.append(path)

        for f in msg.files:
            if f.media:
                suffix = ""
                if f.file_name:
                    suffix = Path(f.file_name).suffix or ""
                path = await self._download_to_temp(f.media, suffix=suffix)
                if path:
                    refs.append(path)

        for v in msg.videos:
            if v.media:
                path = await self._download_to_temp(v.media, suffix=".mp4")
                if path:
                    refs.append(path)

        return refs

    async def _download_to_temp(
        self,
        media: CDNMedia,
        aeskey_override: str | None = None,
        *,
        suffix: str = "",
    ) -> str | None:
        """Download a CDN media file, decrypt, and save to a temp file. Returns file path."""
        import tempfile

        try:
            data = await self.download_media(media, aeskey_override)
            fd, path = tempfile.mkstemp(suffix=suffix, prefix="wechat_")
            os.write(fd, data)
            os.close(fd)
            return path
        except Exception:
            logger.debug(
                "Failed to download CDN media: {}", media.encrypt_query_param[:40]
            )
            return None

    # ── CDN download ─────────────────────────────────────────────────

    async def download_media(
        self, media: CDNMedia, aeskey_override: str | None = None
    ) -> bytes:
        url = f"{CDN_BASE_URL}/download?encrypted_query_param={quote(media.encrypt_query_param)}"
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    raise CryptoError(f"CDN download failed: HTTP {resp.status}")
                ciphertext = await resp.read()

        key_source = aeskey_override or media.aes_key
        if not key_source:
            raise CryptoError("No AES key available for decryption")

        aes_key = decode_aes_key(key_source)
        return decrypt_aes_ecb(ciphertext, aes_key)

    # ── CDN upload ───────────────────────────────────────────────────

    async def upload_media(
        self,
        data: bytes,
        user_id: str,
        media_type: int,
    ) -> tuple[CDNMedia, int]:
        """Upload to CDN. Returns (CDNMedia, encrypted_file_size)."""
        creds = self._require_creds()
        aes_key = generate_aes_key()
        ciphertext = encrypt_aes_ecb(data, aes_key)
        filekey = os.urandom(16).hex()
        raw_md5 = hashlib.md5(data).hexdigest()

        upload_info = await self._api.get_upload_url(
            creds.base_url,
            creds.token,
            {
                "filekey": filekey,
                "media_type": media_type,
                "to_user_id": user_id,
                "rawsize": len(data),
                "rawfilemd5": raw_md5,
                "filesize": len(ciphertext),
                "no_need_thumb": True,
                "aeskey": encode_aes_key_hex(aes_key),
            },
        )

        upload_param = upload_info.get("upload_param")
        if not upload_param:
            raise CryptoError("getuploadurl did not return upload_param")

        upload_url = (
            f"{CDN_BASE_URL}/upload"
            f"?encrypted_query_param={quote(upload_param)}"
            f"&filekey={quote(filekey)}"
        )

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                upload_url,
                data=ciphertext,
                headers={"Content-Type": "application/octet-stream"},
            ) as resp:
                if resp.status >= 400:
                    err_msg = resp.headers.get("x-error-message", f"HTTP {resp.status}")
                    raise CryptoError(f"CDN upload failed: {err_msg}")
                encrypt_query_param = resp.headers.get("x-encrypted-param")
                if not encrypt_query_param:
                    raise CryptoError(
                        "CDN upload succeeded but x-encrypted-param header missing"
                    )

        cdn_media = CDNMedia(
            encrypt_query_param=encrypt_query_param,
            aes_key=encode_aes_key_base64(aes_key),
            encrypt_type=1,
        )
        return cdn_media, len(ciphertext)

    # ── Helpers ──────────────────────────────────────────────────────

    def _require_creds(self) -> Credentials:
        if not self._credentials:
            raise RuntimeError("Not logged in")
        return self._credentials

    def _is_user_allowed(self, user_id: str) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users


def _chunk_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        window = text[:limit]
        cut = -1
        idx = window.rfind("\n\n")
        if idx > limit * 3 // 10:
            cut = idx + 2
        if cut == -1:
            idx = window.rfind("\n")
            if idx > limit * 3 // 10:
                cut = idx + 1
        if cut == -1:
            idx = window.rfind(" ")
            if idx > limit * 3 // 10:
                cut = idx + 1
        if cut == -1:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:]
    return chunks or [""]


# ── Interactive QR login (runs in sync context via asyncio.run) ──────


def _print_qr_terminal(data: str) -> None:
    """Generate and print a QR code in the terminal."""
    try:
        import qrcode

        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=1)
        qr.add_data(data)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print(f"  (qrcode 库未安装，请手动打开此链接扫码)\n  {data}", file=sys.stderr)


async def _qr_login_sync(ui: "SetupUI", cred_path: Path | None) -> Credentials:
    """Run QR login with terminal QR display. Called via asyncio.run()."""
    from datetime import datetime, timezone

    from .ilink import (
        QR_POLL_INTERVAL,
        AuthError,
        ILinkApi,
        save_credentials,
    )

    api = ILinkApi()
    base_url = DEFAULT_BASE_URL

    while True:
        qr = await api.get_qr_code(base_url)
        qr_url = qr["qrcode_img_content"]

        ui.echo("")
        ui.echo("请使用微信扫描以下二维码:")
        ui.echo("")
        _print_qr_terminal(qr_url)
        ui.echo("")
        ui.echo(f"或在浏览器中打开: {qr_url}")
        ui.echo("")

        last_status = ""
        while True:
            status = await api.poll_qr_status(base_url, qr["qrcode"])
            current = status["status"]

            if current != last_status:
                last_status = current
                if current == "scaned":
                    ui.echo("📱 已扫码 — 请在微信中确认登录...")
                elif current == "expired":
                    ui.echo("⏰ 二维码已过期，正在重新获取...")
                elif current == "confirmed":
                    ui.echo("✓ 登录已确认")

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
