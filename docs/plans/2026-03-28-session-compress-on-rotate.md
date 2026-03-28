# 会话轮转压缩 — 实现计划

> **Status: ✅ COMPLETED** (2026-03-28)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动轮转会话时，压缩旧会话历史为极简摘要，注入新会话首条 prompt，使新会话保留前序上下文。通过配置开关控制是否启用。

**Architecture:** 轮转触发时，用 `get_session_messages()` 读取旧会话文本消息 → 用 SDK `query()` 做单轮压缩调用生成摘要 → 摘要存入 `SessionRecord.summary` 持久化 → 新会话首条 prompt 前缀注入摘要。压缩失败不阻塞轮转（静默降级）。

**Tech Stack:** Python 3.12, claude-agent-sdk (`get_session_messages`, `query`), asyncio, pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/chatcc/config.py` | `SessionPolicyConfig` 加 `compress_on_rotate` 开关 |
| Modify | `src/chatcc/project/models.py` | `SessionRecord` 加 `summary` 字段 |
| Create | `src/chatcc/claude/compress.py` | 会话压缩逻辑：读消息 → 格式化 → 调 SDK 压缩 → 返回摘要 |
| Modify | `src/chatcc/claude/task_manager.py` | 轮转时调压缩、注入摘要到首条 prompt |
| Modify | `src/chatcc/channel/compose.py` | 加 "compressing" 通知文案 |
| Create | `tests/test_compress.py` | 压缩模块单元测试 |
| Modify | `tests/test_task_manager.py` | 轮转压缩集成测试 |
| Modify | `tests/test_project_models.py` | `SessionRecord.summary` 序列化测试 |
| Modify | `tests/test_config.py` | `compress_on_rotate` 配置测试 |

---

## Chunk 1: 数据层 — Config 开关 + SessionRecord.summary

### Task 1: SessionPolicyConfig 加 compress_on_rotate

**Files:**
- Modify: `src/chatcc/config.py:65-71` (`SessionPolicyConfig`)
- Modify: `src/chatcc/config.py:170-177` (`load_config` 的 `session_policy` 解析)
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试 — config 默认值**

在 `tests/test_config.py` 底部加：

```python
def test_session_policy_compress_default():
    from chatcc.config import SessionPolicyConfig
    policy = SessionPolicyConfig()
    assert policy.compress_on_rotate is False


def test_session_policy_compress_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
session_policy:
  compress_on_rotate: true
""")
    config = load_config(config_file)
    assert config.session_policy.compress_on_rotate is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_config.py::test_session_policy_compress_default tests/test_config.py::test_session_policy_compress_from_yaml -v`
Expected: FAIL — `SessionPolicyConfig` has no attribute `compress_on_rotate`

- [ ] **Step 3: 实现 — 修改 SessionPolicyConfig**

在 `src/chatcc/config.py` 的 `SessionPolicyConfig` 中加字段：

```python
@dataclass
class SessionPolicyConfig:
    """Tuning knobs for per-project Claude Code session lifecycle."""

    max_tasks_per_session: int = 10
    max_cost_per_session: float = 2.0
    idle_disconnect_seconds: int = 300
    restore_on_startup: bool = True
    compress_on_rotate: bool = False
```

在 `load_config` 的 `session_policy` 解析块中加：

```python
if "session_policy" in expanded:
    sp = expanded["session_policy"]
    config.session_policy = SessionPolicyConfig(
        max_tasks_per_session=sp.get("max_tasks_per_session", 10),
        max_cost_per_session=sp.get("max_cost_per_session", 2.0),
        idle_disconnect_seconds=sp.get("idle_disconnect_seconds", 300),
        restore_on_startup=sp.get("restore_on_startup", True),
        compress_on_rotate=sp.get("compress_on_rotate", False),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/config.py tests/test_config.py
git commit -m "feat(config): add compress_on_rotate session policy option"
```

### Task 2: SessionRecord 加 summary 字段

**Files:**
- Modify: `src/chatcc/project/models.py:64-97` (`SessionRecord`)
- Test: `tests/test_project_models.py`

- [ ] **Step 1: 写失败测试 — summary 字段**

在 `tests/test_project_models.py` 底部加：

```python
def test_session_record_summary_default():
    sr = SessionRecord(session_id="s1", project_name="p")
    assert sr.summary is None


def test_session_record_summary_roundtrip():
    sr = SessionRecord(
        session_id="s1",
        project_name="p",
        summary="项目完成了用户认证模块的实现",
    )
    d = sr.to_dict()
    assert d["summary"] == "项目完成了用户认证模块的实现"
    restored = SessionRecord.from_dict(d)
    assert restored.summary == sr.summary


def test_session_record_from_dict_no_summary():
    """Old JSONL lines without summary field should still parse."""
    d = {
        "session_id": "s1",
        "project_name": "p",
        "started_at": "2025-01-01T00:00:00",
    }
    sr = SessionRecord.from_dict(d)
    assert sr.summary is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_project_models.py::test_session_record_summary_default tests/test_project_models.py::test_session_record_summary_roundtrip tests/test_project_models.py::test_session_record_from_dict_no_summary -v`
Expected: FAIL — `SessionRecord` has no `summary`

- [ ] **Step 3: 实现 — 修改 SessionRecord**

在 `src/chatcc/project/models.py` 的 `SessionRecord` 中：

加字段：
```python
    summary: str | None = None
```

修改 `to_dict`，在 return dict 中加：
```python
    "summary": self.summary,
```

修改 `from_dict`，在构造 `cls(...)` 中加：
```python
    summary=data.get("summary"),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_project_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/project/models.py tests/test_project_models.py
git commit -m "feat(models): add summary field to SessionRecord"
```

---

## Chunk 2: 压缩模块 — compress.py

### Task 3: 创建压缩模块

**Files:**
- Create: `src/chatcc/claude/compress.py`
- Create: `tests/test_compress.py`

**设计要点：**
- `format_messages(messages) -> str`：提取纯文本消息，跳过工具调用，控制总长度
- `compress_session(session_id, project_path, model) -> str | None`：完整压缩流程
- 压缩 prompt 要求极致精简：只保留项目状态、关键决策、未完成事项
- 失败返回 `None`，调用方静默降级

- [ ] **Step 1: 写 format_messages 测试**

创建 `tests/test_compress.py`：

```python
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from chatcc.claude.compress import format_messages


def _msg(role: str, text: str) -> MagicMock:
    """Create a mock SessionMessage."""
    m = MagicMock()
    m.type = role
    m.message = {"role": role, "content": text}
    return m


def _msg_with_blocks(role: str, blocks: list[dict]) -> MagicMock:
    m = MagicMock()
    m.type = role
    m.message = {"role": role, "content": blocks}
    return m


def test_format_messages_simple():
    msgs = [
        _msg("user", "帮我创建一个 hello.py"),
        _msg("assistant", "好的，我来创建文件"),
    ]
    result = format_messages(msgs)
    assert "user: 帮我创建一个 hello.py" in result
    assert "assistant: 好的，我来创建文件" in result


def test_format_messages_skips_tool_blocks():
    msgs = [
        _msg_with_blocks("assistant", [
            {"type": "text", "text": "让我创建文件"},
            {"type": "tool_use", "name": "Write", "input": {"path": "hello.py"}},
        ]),
    ]
    result = format_messages(msgs)
    assert "让我创建文件" in result
    assert "tool_use" not in result
    assert "Write" not in result


def test_format_messages_empty():
    assert format_messages([]) == ""


def test_format_messages_truncates_long_content():
    long_text = "x" * 100_000
    msgs = [_msg("user", long_text)]
    result = format_messages(msgs, max_chars=5000)
    assert len(result) <= 6000  # some overhead for role prefix
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_compress.py -v`
Expected: FAIL — `chatcc.claude.compress` module not found

- [ ] **Step 3: 实现 format_messages**

创建 `src/chatcc/claude/compress.py`：

```python
"""Compress a Claude Code session into a concise summary."""

from __future__ import annotations

from typing import Any

from loguru import logger


def format_messages(
    messages: list[Any],
    *,
    max_chars: int = 30_000,
) -> str:
    """Extract text-only content from session messages.

    Skips tool_use / tool_result blocks to keep the input lean.
    Truncates from the beginning when exceeding *max_chars* so the
    most recent context is preserved.
    """
    lines: list[str] = []
    for msg in messages:
        role = getattr(msg, "type", None) or "unknown"
        raw = getattr(msg, "message", None)
        if not isinstance(raw, dict):
            continue
        content = raw.get("content", "")
        if isinstance(content, str):
            lines.append(f"{role}: {content}")
        elif isinstance(content, list):
            texts = [
                b["text"] for b in content
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            if texts:
                lines.append(f"{role}: {''.join(texts)}")

    full = "\n".join(lines)
    if len(full) > max_chars:
        full = full[-max_chars:]
        cut = full.find("\n")
        if cut > 0:
            full = full[cut + 1:]
    return full
```

- [ ] **Step 4: 运行 format_messages 测试确认通过**

Run: `pytest tests/test_compress.py -v`
Expected: ALL PASS

- [ ] **Step 5: 写 compress_session 测试**

在 `tests/test_compress.py` 底部加：

```python
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
@patch("chatcc.claude.compress.get_session_messages")
@patch("chatcc.claude.compress.query")
async def test_compress_session_success(mock_query, mock_get_msgs):
    from chatcc.claude.compress import compress_session

    mock_get_msgs.return_value = [
        _msg("user", "创建用户认证模块"),
        _msg("assistant", "好的，我已经完成了 JWT 认证的实现"),
    ]

    # Simulate query() yielding a ResultMessage with the summary
    result_msg = MagicMock()
    result_msg.__class__.__name__ = "ResultMessage"
    result_msg.result = "完成了JWT认证模块"
    type(result_msg).result = property(lambda self: "完成了JWT认证模块")

    from chatcc.claude.compress import ResultMessage as RM

    async def fake_query(**kwargs):
        rm = MagicMock(spec=RM)
        rm.result = "完成了JWT认证模块"
        yield rm

    mock_query.side_effect = fake_query

    summary = await compress_session("sess-1", "/tmp/proj")
    assert summary is not None
    assert "JWT" in summary or "认证" in summary
    mock_get_msgs.assert_called_once()


@pytest.mark.asyncio
@patch("chatcc.claude.compress.get_session_messages")
async def test_compress_session_no_messages(mock_get_msgs):
    from chatcc.claude.compress import compress_session

    mock_get_msgs.return_value = []
    summary = await compress_session("sess-1", "/tmp/proj")
    assert summary is None


@pytest.mark.asyncio
@patch("chatcc.claude.compress.get_session_messages")
async def test_compress_session_error_returns_none(mock_get_msgs):
    from chatcc.claude.compress import compress_session

    mock_get_msgs.side_effect = RuntimeError("SDK error")
    summary = await compress_session("sess-1", "/tmp/proj")
    assert summary is None
```

- [ ] **Step 6: 实现 compress_session**

在 `src/chatcc/claude/compress.py` 底部加：

```python
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    get_session_messages,
    query,
)

_COMPRESS_PROMPT = (
    "请将以下对话历史压缩为一段极简摘要。只保留：\n"
    "1. 项目当前状态（已完成/进行中的工作）\n"
    "2. 关键技术决策和约束\n"
    "3. 未完成的待办事项\n"
    "忽略所有工具调用细节和中间调试过程。用中文，控制在 300 字以内。\n\n"
    "---对话历史---\n{conversation}\n---\n\n"
    "极简摘要："
)


async def compress_session(
    session_id: str,
    project_path: str,
    *,
    model: str | None = None,
) -> str | None:
    """Compress a session's conversation into a concise summary.

    Returns None if compression fails or the session has no meaningful content.
    Never raises — errors are logged and silently swallowed.
    """
    try:
        messages = get_session_messages(session_id, directory=project_path)
    except Exception:
        logger.opt(exception=True).debug(
            "Failed to read session {} messages", session_id[:12]
        )
        return None

    if not messages:
        return None

    conversation = format_messages(messages)
    if not conversation.strip():
        return None

    prompt = _COMPRESS_PROMPT.format(conversation=conversation)

    try:
        options = ClaudeAgentOptions(
            max_turns=1,
            model=model,
        )
        summary: str | None = None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, ResultMessage) and msg.result:
                summary = msg.result
        return summary
    except Exception:
        logger.opt(exception=True).debug(
            "Failed to compress session {}", session_id[:12]
        )
        return None
```

- [ ] **Step 7: 运行全部压缩测试确认通过**

Run: `pytest tests/test_compress.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/chatcc/claude/compress.py tests/test_compress.py
git commit -m "feat(compress): add session compression module"
```

---

## Chunk 3: TaskManager 集成 + 通知

### Task 4: compose 加 compressing 通知

**Files:**
- Modify: `src/chatcc/channel/compose.py:129-139`

- [ ] **Step 1: 写测试**

在 `tests/test_compose.py` 底部加：

```python
from chatcc.channel.compose import compose_session_rotated
from chatcc.channel.message import ProgressElement


def test_compose_session_rotated_compressing():
    rich = compose_session_rotated("myapp", "compressing")
    elems = [e for e in rich.elements if isinstance(e, ProgressElement)]
    assert len(elems) == 1
    assert "压缩" in elems[0].text
```

- [ ] **Step 2: 实现 — 加 reason 映射**

在 `src/chatcc/channel/compose.py` 的 `compose_session_rotated` 的 `reasons` dict 中加一行：

```python
    "compressing": "🗜️ 正在压缩会话上下文...",
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_compose.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/chatcc/channel/compose.py tests/test_compose.py
git commit -m "feat(compose): add compressing notification reason"
```

### Task 5: TaskManager 集成压缩轮转

**Files:**
- Modify: `src/chatcc/claude/task_manager.py`
- Modify: `tests/test_task_manager.py`

**设计要点：**
- `_pending_summaries: dict[str, str]` — 内存中缓存待注入的摘要
- `_rotate_session()` 改名内部逻辑：若 `compress_on_rotate` 开启，先压缩后轮转
- `_run_task_item()` 中，若有 pending summary，前缀注入到 prompt
- 进程重启恢复：在 `_restore_session_id()` 中检查最近一个 closed session 的 summary

- [ ] **Step 1: 写测试 — pending summary 注入到 prompt**

在 `tests/test_task_manager.py` 底部加：

```python
# ── Session compression on rotate ─────────────────────────────────


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_pending_summary_injected_into_prompt(MockSession, mock_pm):
    """When a pending summary exists for a project, the first task prompt
    should be prefixed with the compressed context."""
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "new-sess", "cost": 0.01}
    )
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    tm._pending_summaries["proj-a"] = "之前完成了JWT认证"

    await tm.submit_task("proj-a", "继续实现权限系统")
    await asyncio.sleep(0.3)

    call_args = mock_client.query.call_args
    prompt_sent = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "之前完成了JWT认证" in prompt_sent
    assert "继续实现权限系统" in prompt_sent
    # Summary consumed after first use
    assert "proj-a" not in tm._pending_summaries


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_no_summary_no_prefix(MockSession, mock_pm):
    """Without a pending summary, the prompt is sent as-is."""
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "s1", "cost": 0.01}
    )
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    await tm.submit_task("proj-a", "build feature")
    await asyncio.sleep(0.3)

    mock_client.query.assert_awaited_once_with("build feature")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_task_manager.py::test_pending_summary_injected_into_prompt tests/test_task_manager.py::test_no_summary_no_prefix -v`
Expected: FAIL — `TaskManager` has no `_pending_summaries`

- [ ] **Step 3: 实现 — _pending_summaries 和 prompt 注入**

在 `src/chatcc/claude/task_manager.py` 的 `TaskManager.__init__` 中加：

```python
        self._pending_summaries: dict[str, str] = {}
```

在 `_run_task_item` 方法中，在 `await client.query(queued.prompt)` **之前**，加摘要注入：

```python
        prompt = queued.prompt
        carry_over = self._pending_summaries.pop(project_name, None)
        if carry_over:
            prompt = (
                f"[前序会话上下文]\n{carry_over}\n"
                f"[/前序会话上下文]\n\n{prompt}"
            )
```

然后把 `await client.query(queued.prompt)` 改为 `await client.query(prompt)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_task_manager.py::test_pending_summary_injected_into_prompt tests/test_task_manager.py::test_no_summary_no_prefix -v`
Expected: PASS

- [ ] **Step 5: 写测试 — 压缩轮转 e2e**

在 `tests/test_task_manager.py` 底部加：

```python
from chatcc.config import SessionPolicyConfig


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.compress_session", new_callable=AsyncMock)
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_rotate_with_compress(mock_compress, MockSession, mock_pm):
    """When compress_on_rotate is True, rotation should compress and store summary."""
    mock_compress.return_value = "完成了用户认证"

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.disconnect = AsyncMock()
    MockSession.return_value = mock_session

    policy = SessionPolicyConfig(compress_on_rotate=True, max_tasks_per_session=1)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm._sessions["proj-a"] = mock_session

    # Seed a session log so close_session works
    sl = tm.get_session_log("proj-a")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a",
        task_ids=["t1"], status="active",
    ))

    await tm._rotate_session("proj-a")

    mock_compress.assert_awaited_once_with(
        "old-sess", mock_session.project.path, model=mock_session.project.config.model,
    )
    assert tm._pending_summaries.get("proj-a") == "完成了用户认证"


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.compress_session", new_callable=AsyncMock)
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_rotate_compress_disabled(mock_compress, MockSession, mock_pm):
    """When compress_on_rotate is False (default), no compression happens."""
    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.disconnect = AsyncMock()
    MockSession.return_value = mock_session

    policy = SessionPolicyConfig(compress_on_rotate=False)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm._sessions["proj-a"] = mock_session

    sl = tm.get_session_log("proj-a")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a", status="active",
    ))

    await tm._rotate_session("proj-a")

    mock_compress.assert_not_awaited()
    assert "proj-a" not in tm._pending_summaries


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.compress_session", new_callable=AsyncMock)
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_rotate_compress_failure_degrades(mock_compress, MockSession, mock_pm):
    """Compression failure should not block rotation."""
    mock_compress.return_value = None  # compression failed

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.disconnect = AsyncMock()
    MockSession.return_value = mock_session

    policy = SessionPolicyConfig(compress_on_rotate=True, max_tasks_per_session=1)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm._sessions["proj-a"] = mock_session

    sl = tm.get_session_log("proj-a")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a", status="active",
    ))

    await tm._rotate_session("proj-a")

    # Rotation still completed
    mock_session.disconnect.assert_awaited()
    assert mock_session.active_session_id is None
    assert "proj-a" not in tm._pending_summaries
```

- [ ] **Step 6: 实现 — _rotate_session 压缩集成**

在 `src/chatcc/claude/task_manager.py` 顶部加导入：

```python
from chatcc.claude.compress import compress_session
```

重写 `_rotate_session`：

```python
    async def _rotate_session(self, project_name: str) -> None:
        session = self._sessions.get(project_name)
        if not session:
            return

        # Compress before closing (if enabled and session has an ID)
        if (
            self._policy.compress_on_rotate
            and session.active_session_id
        ):
            await self._notify(
                project_name,
                compose_session_rotated(project_name, "compressing"),
            )
            summary = await compress_session(
                session.active_session_id,
                session.project.path,
                model=session.project.config.model,
            )
            if summary:
                self._pending_summaries[project_name] = summary
                # Persist on the closing session record
                session_log = self.get_session_log(project_name)
                if session_log:
                    record = session_log.get(session.active_session_id)
                    if record:
                        record.summary = summary
                        session_log.append(record)

        self.close_session(project_name)
        try:
            await session.disconnect()
        except Exception:
            pass
        session.active_session_id = None
        session.task_state = TaskState.IDLE
        await self._notify(
            project_name,
            compose_session_rotated(project_name, "idle"),
        )
```

- [ ] **Step 7: 运行全部测试确认通过**

Run: `pytest tests/test_task_manager.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add src/chatcc/claude/task_manager.py tests/test_task_manager.py
git commit -m "feat(task_manager): integrate session compression on rotation"
```

### Task 6: 进程重启恢复 pending summary

**Files:**
- Modify: `src/chatcc/claude/task_manager.py:86-130` (`_restore_session_id`)
- Modify: `tests/test_task_manager.py`

**设计要点：** 如果进程重启时发现最近关闭的 session 有 summary，且当前没有 active session（说明刚轮转完还没发过新任务），则恢复 pending summary。

- [ ] **Step 1: 写测试**

在 `tests/test_task_manager.py` 底部加：

```python
def test_restore_recovers_pending_summary(mock_pm):
    """On restart, if the most recent closed session has a summary,
    it should be loaded into _pending_summaries."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="old-sess",
        project_name="proj-a",
        status="closed",
        summary="完成了数据库迁移",
    ))

    policy = SessionPolicyConfig(compress_on_rotate=True)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm.get_session("proj-a")

    assert tm._pending_summaries.get("proj-a") == "完成了数据库迁移"


def test_restore_no_summary_when_disabled(mock_pm):
    """When compress_on_rotate is off, don't restore summaries."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="old-sess",
        project_name="proj-a",
        status="closed",
        summary="完成了数据库迁移",
    ))

    policy = SessionPolicyConfig(compress_on_rotate=False)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm.get_session("proj-a")

    assert "proj-a" not in tm._pending_summaries


def test_restore_no_summary_when_active_session_exists(mock_pm):
    """If there's an active session (not yet rotated), don't load old summary."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a",
        status="closed", summary="旧摘要",
    ))
    sl.append(SessionRecord(
        session_id="current-sess", project_name="proj-a",
        status="active",
    ))

    policy = SessionPolicyConfig(compress_on_rotate=True)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm.get_session("proj-a")

    assert "proj-a" not in tm._pending_summaries
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_task_manager.py::test_restore_recovers_pending_summary -v`
Expected: FAIL — no summary recovery logic

- [ ] **Step 3: 实现 — _restore_session_id 恢复 summary**

在 `_restore_session_id` 方法末尾（`return` 或函数结束之前），加入 summary 恢复逻辑。在所有 `return` 路径之后（当 `session.active_session_id` 仍为 `None` 时），检查最近关闭的 session：

```python
        # If no active session but compress is on, check for a pending summary
        # from the most recently closed session (rotation completed before restart).
        if (
            not session.active_session_id
            and self._policy.compress_on_rotate
            and session_log
        ):
            closed = [
                r for r in session_log.get_all()
                if r.status == "closed" and r.summary
            ]
            if closed:
                closed.sort(key=lambda r: r.started_at)
                self._pending_summaries[project_name] = closed[-1].summary
                logger.info(
                    "Restored pending summary for '{}' from session {}",
                    project_name,
                    closed[-1].session_id[:12],
                )
```

注意：这段逻辑需要在 `_restore_session_id` 已经尝试过恢复 active session 之后执行，且仅在 `session.active_session_id` 仍为 `None` 时（说明无 active session，即上次轮转后没有新任务）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_task_manager.py::test_restore_recovers_pending_summary tests/test_task_manager.py::test_restore_no_summary_when_disabled tests/test_task_manager.py::test_restore_no_summary_when_active_session_exists -v`
Expected: ALL PASS

- [ ] **Step 5: 运行全部测试**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/chatcc/claude/task_manager.py tests/test_task_manager.py
git commit -m "feat(task_manager): restore pending summary on process restart"
```

---

## 验证清单

- [ ] `pytest tests/ -v` 全部通过
- [ ] `compress_on_rotate: false`（默认）时行为与之前完全一致
- [ ] `compress_on_rotate: true` 时：轮转触发压缩 → 新会话首条 prompt 带摘要前缀
- [ ] 压缩失败时静默降级，轮转正常完成
- [ ] 进程重启后 pending summary 从 JSONL 恢复
- [ ] `context_too_long` 和 `process_error` 轮转不受影响（不压缩）
