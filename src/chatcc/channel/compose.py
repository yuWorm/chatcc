"""Construct RichMessage instances for common notification scenarios.

This is the single entry-point for building rich messages — callers should
use these helpers instead of assembling elements by hand.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from chatcc.channel.message import (
    ActionButton,
    ActionGroup,
    CodeElement,
    DividerElement,
    MessageElement,
    ProgressElement,
    RichMessage,
    TextElement,
)

if TYPE_CHECKING:
    from chatcc.approval.table import PendingApproval

# ── Approval ──────────────────────────────────────────────────────────


def compose_approval(
    project: str,
    tool_name: str,
    summary: str,
    approval_id: int,
) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[
            TextElement("⚠️ 危险操作待确认"),
            TextElement(f"{tool_name}: {summary}"),
            ActionGroup([
                ActionButton("✅ 确认", f"/y {approval_id}"),
                ActionButton("❌ 拒绝", f"/n {approval_id}"),
            ]),
        ],
    )


def compose_conflict_choice(
    project: str,
    prompt_preview: str,
    approval_id: int,
) -> RichMessage:
    preview = prompt_preview[:120]
    return RichMessage(
        project_tag=project,
        elements=[
            TextElement(f"⚠️ 项目 [{project}] 正在执行任务"),
            TextElement(f"新任务: {preview}"),
            ActionGroup([
                ActionButton(
                    "📋 排队等待",
                    f"/resolve {approval_id} queue",
                    style="primary",
                ),
                ActionButton(
                    "⚡ 打断执行",
                    f"/resolve {approval_id} interrupt",
                    style="default",
                ),
                ActionButton(
                    "❌ 取消",
                    f"/resolve {approval_id} cancel",
                    style="danger",
                ),
            ]),
        ],
    )


def compose_confirmation(
    project: str,
    description: str,
    approval_id: int,
) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[
            TextElement(f"⚠️ {description}"),
            ActionGroup([
                ActionButton(
                    "✅ 确认",
                    f"/resolve {approval_id} approve",
                    style="primary",
                ),
                ActionButton(
                    "❌ 取消",
                    f"/resolve {approval_id} deny",
                    style="danger",
                ),
            ]),
        ],
    )


# ── Task lifecycle ────────────────────────────────────────────────────


def compose_task_completed(project: str, cost: float) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[ProgressElement(f"✅ 任务完成 (${cost:.4f})", project=project)],
    )


def compose_task_failed(project: str, error: str) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[ProgressElement(f"❌ 任务失败: {error}", project=project)],
    )


def compose_task_interrupted(project: str) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[ProgressElement("⏸️ 任务已中断", project=project)],
    )


def compose_session_rotated(project: str, reason: str) -> RichMessage:
    reasons = {
        "idle": "🔄 会话已自动轮转，开启新对话",
        "context_too_long": "🔄 会话上下文过长，自动切换新会话重试...",
        "process_error": "🔄 Claude Code 进程异常，正在重置连接重试...",
    }
    text = reasons.get(reason, f"🔄 {reason}")
    return RichMessage(
        project_tag=project,
        elements=[ProgressElement(text, project=project)],
    )


def compose_retry_success(project: str, cost: float) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[ProgressElement(f"✅ 重试成功 (${cost:.4f})", project=project)],
    )


def compose_retry_failed(project: str, error: str) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[ProgressElement(f"❌ 重试失败: {error}", project=project)],
    )


# ── Command responses ─────────────────────────────────────────────────


def compose_pending_list(pending: list[PendingApproval]) -> RichMessage:
    if not pending:
        return RichMessage(elements=[TextElement("暂无待确认操作")])

    elements: list[MessageElement] = [
        TextElement(f"待确认操作 ({len(pending)} 条):"),
    ]
    for i, p in enumerate(pending):
        elements.append(
            TextElement(f"#{p.id} [{p.project}] {p.tool_name}: {p.input_summary}")
        )
        if p.is_binary:
            elements.append(ActionGroup([
                ActionButton("✅ 确认", f"/y {p.id}"),
                ActionButton("❌ 拒绝", f"/n {p.id}"),
            ]))
        else:
            buttons = [
                ActionButton(label, f"/resolve {p.id} {value}")
                for label, value in (p.choices or [])
            ]
            elements.append(ActionGroup(buttons))
        if i < len(pending) - 1:
            elements.append(DividerElement())

    return RichMessage(elements=elements)


def compose_help(help_text: str) -> RichMessage:
    return RichMessage(elements=[TextElement(help_text)])


# ── Agent markdown parsing ────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(
    r"^```(\w*)\n(.*?)^```",
    re.MULTILINE | re.DOTALL,
)


def parse_markdown(
    text: str,
    project: str | None = None,
) -> RichMessage:
    """Split markdown text into TextElement / CodeElement sequences.

    Only fenced code blocks (``` ... ```) are extracted; all other content
    stays as-is inside TextElement (channels handle inline markdown in
    their own render methods).
    """
    elements: list[MessageElement] = []
    last_end = 0

    for m in _CODE_FENCE_RE.finditer(text):
        before = text[last_end:m.start()].strip()
        if before:
            elements.append(TextElement(before))
        lang = m.group(1) or ""
        code = m.group(2).rstrip("\n")
        elements.append(CodeElement(code=code, language=lang))
        last_end = m.end()

    trailing = text[last_end:].strip()
    if trailing:
        elements.append(TextElement(trailing))

    if not elements:
        elements.append(TextElement(""))

    return RichMessage(elements=elements, project_tag=project)
