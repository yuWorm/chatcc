# 主 Agent 内联确认 — 泛化审批表实现计划

> **Status: ✅ COMPLETED** (2026-03-28)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让主 Agent 的 pydantic-ai tools（`send_to_claude` conflict、`interrupt_task`）能直接通过 ApprovalTable 发送带按钮的确认卡片，用户点击即完成选择，无需 agent 中间传话。

**Architecture:** 将 `ApprovalTable` 的 `Future[bool]` 泛化为 `Future[str]`，统一处理二选一（approve/deny）和多选（queue/interrupt/cancel）。新增 `/resolve {id} {value}` 拦截命令处理多选项。主 Agent tools 通过 `AgentDeps.approval_table` + `AgentDeps.send_fn` 直接发卡片并 await future。

**Tech Stack:** Python 3.12, asyncio, pydantic-ai, 飞书/Telegram 交互卡片

### Additional work completed beyond original plan:
- **fix(feishu):** Monkey-patch lark_oapi WS client to handle `MessageType.CARD` frames (SDK bug: drops card callbacks in WebSocket mode)
- **feat(feishu):** Return toast + updated card on button click to stop Feishu spinner
- **feat(feishu):** Card cache to preserve original card content in callback replacement cards

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/chatcc/approval/table.py` | `Future[bool]` → `Future[str]`, 加 choices, resolve() |
| Modify | `src/chatcc/channel/message.py` | `ActionButton` 加 `style` 字段 |
| Modify | `src/chatcc/channel/compose.py` | 新增 `compose_conflict_choice`, `compose_confirmation`; 更新 `compose_pending_list` |
| Modify | `src/chatcc/channel/__init__.py` | re-export 新 compose 函数 |
| Modify | `src/chatcc/command/commands.py` | 注册 `/resolve` 拦截命令 |
| Modify | `src/chatcc/app.py` | 处理 `/resolve`, 适配 `approve/deny` → `resolve("approve"/"deny")` |
| Modify | `src/chatcc/claude/session.py` | `_permission_handler` 适配 `Future[str]` |
| Modify | `src/chatcc/tools/session_tools.py` | `send_to_claude` conflict 内联确认, `interrupt_task` 确认 |
| Modify | `src/chatcc/channel/feishu.py` | 按钮 style 映射 |
| Modify | `tests/test_approval.py` | 新 API 测试 |
| Modify | `tests/test_app_integration.py` | `/resolve` 命令测试 |
| Create | `tests/test_compose.py` | compose helpers 测试 |
| Modify | `tests/test_task_manager.py` | 如需调整 |

---

## Chunk 1: ApprovalTable 泛化 + ActionButton 样式

### Task 1: 泛化 ApprovalTable — Future[str] + choices + resolve()

**Files:**
- Modify: `src/chatcc/approval/table.py`
- Test: `tests/test_approval.py`

**设计要点:**
- `PendingApproval.future` 从 `asyncio.Future[bool]` 改为 `asyncio.Future[str]`
- 新增 `choices: list[tuple[str, str]] | None` — `(label, value)` 对; `None` 表示二选一
- 新增 `resolve(id, value)` 方法 — 通用解决入口
- `approve(id)` → 调用 `resolve(id, "approve")`
- `deny(id)` → 调用 `resolve(id, "deny")`
- 新增 `request_choice(project, tool_name, summary, choices)` — 带选项的请求
- `request_approval` 保持签名不变，内部调 `_request(... choices=None)`
- `approve_oldest` / `deny_oldest` / `approve_all` / `deny_all` — 只处理 choices=None 的二选一项
- `list_pending()` 返回值不变（PendingApproval 列表），但对象多了 choices 字段

- [x] **Step 1: 写 test — resolve() 方法**

```python
# tests/test_approval.py — 新增

async def test_resolve_approve():
    table = ApprovalTable()
    future, aid = table.request_approval("proj", "Bash", "rm -rf /")
    assert table.resolve(aid, "approve")
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == "approve"
    assert table.pending_count == 0


async def test_resolve_deny():
    table = ApprovalTable()
    future, aid = table.request_approval("proj", "Bash", "rm -rf /")
    assert table.resolve(aid, "deny")
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == "deny"


async def test_resolve_invalid_id():
    table = ApprovalTable()
    assert not table.resolve(999, "approve")
```

- [x] **Step 2: 写 test — request_choice() + resolve()**

```python
async def test_request_choice_and_resolve():
    table = ApprovalTable()
    choices = [("排队", "queue"), ("打断", "interrupt"), ("取消", "cancel")]
    future, aid = table.request_choice(
        project="myapp",
        tool_name="send_to_claude",
        input_summary="项目正在执行任务",
        choices=choices,
    )
    assert table.pending_count == 1
    entry = table.list_pending()[0]
    assert entry.choices == choices

    table.resolve(aid, "interrupt")
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == "interrupt"
    assert table.pending_count == 0


async def test_approve_all_skips_choice_items():
    table = ApprovalTable()
    f_binary, _ = table.request_approval("a", "Bash", "cmd")
    f_choice, _ = table.request_choice(
        "b", "send_to_claude", "conflict",
        choices=[("排队", "queue"), ("取消", "cancel")],
    )
    count = table.approve_all()
    assert count == 1
    assert await asyncio.wait_for(f_binary, timeout=1.0) == "approve"
    assert table.pending_count == 1  # choice item still pending
```

- [x] **Step 3: 运行测试，确认失败**

```bash
pytest tests/test_approval.py -v
```
Expected: FAIL — `resolve` 方法不存在, `request_choice` 不存在

- [x] **Step 4: 实现 ApprovalTable 泛化**

`src/chatcc/approval/table.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PendingApproval:
    id: int
    project: str
    tool_name: str
    input_summary: str
    future: asyncio.Future
    choices: list[tuple[str, str]] | None = None
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_binary(self) -> bool:
        return self.choices is None


class ApprovalTable:
    def __init__(self):
        self._pending: dict[int, PendingApproval] = {}
        self._next_id = 1

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def _request(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
        choices: list[tuple[str, str]] | None = None,
    ) -> tuple[asyncio.Future[str], int]:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[str] = loop.create_future()
        approval_id = self._next_id
        entry = PendingApproval(
            id=approval_id,
            project=project,
            tool_name=tool_name,
            input_summary=input_summary,
            future=future,
            choices=choices,
        )
        self._pending[approval_id] = entry
        self._next_id += 1
        return future, approval_id

    def request_approval(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
    ) -> tuple[asyncio.Future[str], int]:
        return self._request(project, tool_name, input_summary, choices=None)

    def request_choice(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
        choices: list[tuple[str, str]],
    ) -> tuple[asyncio.Future[str], int]:
        return self._request(project, tool_name, input_summary, choices=choices)

    def resolve(self, approval_id: int, value: str) -> bool:
        entry = self._pending.pop(approval_id, None)
        if entry and not entry.future.done():
            entry.future.set_result(value)
            return True
        return False

    def approve(self, approval_id: int) -> bool:
        return self.resolve(approval_id, "approve")

    def deny(self, approval_id: int) -> bool:
        return self.resolve(approval_id, "deny")

    def approve_oldest(self) -> bool:
        for aid, entry in sorted(self._pending.items()):
            if entry.is_binary:
                return self.approve(aid)
        return False

    def deny_oldest(self) -> bool:
        for aid, entry in sorted(self._pending.items()):
            if entry.is_binary:
                return self.deny(aid)
        return False

    def approve_all(self) -> int:
        count = 0
        for aid in list(self._pending.keys()):
            entry = self._pending.get(aid)
            if entry and entry.is_binary:
                if self.approve(aid):
                    count += 1
        return count

    def deny_all(self) -> int:
        count = 0
        for aid in list(self._pending.keys()):
            entry = self._pending.get(aid)
            if entry and entry.is_binary:
                if self.deny(aid):
                    count += 1
        return count

    def list_pending(self) -> list[PendingApproval]:
        return sorted(self._pending.values(), key=lambda x: x.id)
```

- [x] **Step 5: 更新现有测试 — assert result is True → assert result == "approve"**

```python
# tests/test_approval.py — 更新现有测试

async def test_request_and_approve():
    table = ApprovalTable()
    future, approval_id = table.request_approval(
        project="myapp", tool_name="Bash", input_summary="rm -rf dist/",
    )
    assert approval_id == 1
    assert table.pending_count == 1
    table.approve(1)
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == "approve"  # was: assert result is True
    assert table.pending_count == 0


async def test_request_and_deny():
    table = ApprovalTable()
    future, approval_id = table.request_approval(
        project="myapp", tool_name="Bash", input_summary="sudo rm /",
    )
    assert approval_id == 1
    table.deny(1)
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result == "deny"  # was: assert result is False


async def test_approve_oldest():
    table = ApprovalTable()
    f1, _ = table.request_approval("proj-a", "Bash", "cmd1")
    f2, _ = table.request_approval("proj-b", "Bash", "cmd2")
    assert table.pending_count == 2
    table.approve_oldest()
    r1 = await asyncio.wait_for(f1, timeout=1.0)
    assert r1 == "approve"  # was: assert r1 is True
    assert table.pending_count == 1


async def test_approve_all():
    table = ApprovalTable()
    f1, _ = table.request_approval("a", "Bash", "c1")
    f2, _ = table.request_approval("b", "Bash", "c2")
    table.approve_all()
    assert await asyncio.wait_for(f1, timeout=1.0) == "approve"
    assert await asyncio.wait_for(f2, timeout=1.0) == "approve"
    assert table.pending_count == 0
```

- [x] **Step 6: 运行全部 approval 测试**

```bash
pytest tests/test_approval.py -v
```
Expected: ALL PASS

- [x] **Step 7: Commit**

```bash
git add src/chatcc/approval/table.py tests/test_approval.py
git commit -m "feat(approval): generalize ApprovalTable — Future[str], choices, resolve()"
```

### Task 2: ActionButton 加 style 字段

**Files:**
- Modify: `src/chatcc/channel/message.py`
- Modify: `src/chatcc/channel/feishu.py`

**设计要点:**
- `ActionButton` 新增 `style: str = ""` — 可选值: `"primary"`, `"danger"`, `"default"`, `""` (由渠道自行决定)
- 飞书渲染: 有 style 用 style，无 style 保持原逻辑 (`/y` → primary, 其他 → danger)
- Telegram/CLI 不受影响（Telegram inline 按钮无 style 概念，CLI 纯文本）

- [x] **Step 1: 修改 ActionButton 定义**

`src/chatcc/channel/message.py` — 给 `ActionButton` 加 `style` 字段:

```python
@dataclass
class ActionButton:
    label: str
    command: str
    style: str = ""
```

- [x] **Step 2: 修改飞书渲染逻辑**

`src/chatcc/channel/feishu.py` render() 中 `ActionGroup` 分支:

```python
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
```

- [x] **Step 3: 运行现有测试确认不破坏**

```bash
pytest tests/ -v --timeout=10
```
Expected: ALL PASS (style="" 走原有逻辑)

- [x] **Step 4: Commit**

```bash
git add src/chatcc/channel/message.py src/chatcc/channel/feishu.py
git commit -m "feat(channel): add style field to ActionButton for flexible button rendering"
```

---

## Chunk 2: Compose helpers + /resolve 命令

### Task 3: 新增 compose helpers

**Files:**
- Modify: `src/chatcc/channel/compose.py`
- Modify: `src/chatcc/channel/__init__.py`
- Create: `tests/test_compose.py`

**设计要点:**
- `compose_conflict_choice(project, prompt_preview, approval_id)` — 三按钮: 排队/打断/取消
- `compose_confirmation(project, description, approval_id)` — 二按钮: 确认/取消
- `compose_pending_list` — choice 项渲染选项按钮而非 ✅/❌
- 按钮使用 `/resolve {id} {value}` 命令格式

- [x] **Step 1: 写 test — compose_conflict_choice**

```python
# tests/test_compose.py

from chatcc.channel.compose import (
    compose_conflict_choice,
    compose_confirmation,
    compose_pending_list,
)
from chatcc.channel.message import ActionGroup, TextElement


def test_compose_conflict_choice():
    rich = compose_conflict_choice("myapp", "build feature X", 5)
    assert rich.project_tag == "myapp"
    texts = [e for e in rich.elements if isinstance(e, TextElement)]
    assert any("myapp" in t.content for t in texts)
    assert any("build feature X" in t.content for t in texts)
    groups = [e for e in rich.elements if isinstance(e, ActionGroup)]
    assert len(groups) == 1
    buttons = groups[0].buttons
    assert len(buttons) == 3
    commands = [b.command for b in buttons]
    assert "/resolve 5 queue" in commands
    assert "/resolve 5 interrupt" in commands
    assert "/resolve 5 cancel" in commands
```

- [x] **Step 2: 写 test — compose_confirmation**

```python
def test_compose_confirmation():
    rich = compose_confirmation("myapp", "确定要中断当前任务？", 7)
    assert rich.project_tag == "myapp"
    groups = [e for e in rich.elements if isinstance(e, ActionGroup)]
    assert len(groups) == 1
    buttons = groups[0].buttons
    assert len(buttons) == 2
    commands = [b.command for b in buttons]
    assert "/resolve 7 approve" in commands
    assert "/resolve 7 deny" in commands
```

- [x] **Step 3: 写 test — compose_pending_list 混合项**

```python
def test_compose_pending_list_with_choices():
    from chatcc.approval.table import PendingApproval
    import asyncio

    loop = asyncio.new_event_loop()
    items = [
        PendingApproval(
            id=1, project="a", tool_name="Bash",
            input_summary="rm -rf /",
            future=loop.create_future(),
        ),
        PendingApproval(
            id=2, project="b", tool_name="send_to_claude",
            input_summary="项目正在执行任务",
            future=loop.create_future(),
            choices=[("排队", "queue"), ("打断", "interrupt"), ("取消", "cancel")],
        ),
    ]
    rich = compose_pending_list(items)
    groups = [e for e in rich.elements if isinstance(e, ActionGroup)]
    assert len(groups) == 2
    # binary item has /y /n
    assert any("/y 1" in b.command for b in groups[0].buttons)
    # choice item has /resolve
    assert any("/resolve 2" in b.command for b in groups[1].buttons)
    loop.close()
```

- [x] **Step 4: 运行测试确认失败**

```bash
pytest tests/test_compose.py -v
```
Expected: FAIL — `compose_conflict_choice` 和 `compose_confirmation` 不存在

- [x] **Step 5: 实现 compose helpers**

`src/chatcc/channel/compose.py` — 在 `# ── Command responses` 前插入:

```python
# ── Choice / confirmation cards ──────────────────────────────────


def compose_conflict_choice(
    project: str,
    prompt_preview: str,
    approval_id: int,
) -> RichMessage:
    return RichMessage(
        project_tag=project,
        elements=[
            TextElement(f"⚠️ 项目 [{project}] 正在执行任务"),
            TextElement(f"新任务: {prompt_preview[:120]}"),
            ActionGroup([
                ActionButton("📋 排队等待", f"/resolve {approval_id} queue", style="primary"),
                ActionButton("⚡ 打断执行", f"/resolve {approval_id} interrupt", style="default"),
                ActionButton("❌ 取消", f"/resolve {approval_id} cancel", style="danger"),
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
                ActionButton("✅ 确认", f"/resolve {approval_id} approve", style="primary"),
                ActionButton("❌ 取消", f"/resolve {approval_id} deny", style="danger"),
            ]),
        ],
    )
```

- [x] **Step 6: 更新 compose_pending_list 支持 choice 项**

```python
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
```

- [x] **Step 7: 更新 `__init__.py` re-export**

`src/chatcc/channel/__init__.py` — 加入:

```python
from chatcc.channel.compose import (
    # ... existing ...
    compose_conflict_choice,
    compose_confirmation,
)
```

并在 `__all__` 中添加 `"compose_conflict_choice"`, `"compose_confirmation"`。

- [x] **Step 8: 运行测试**

```bash
pytest tests/test_compose.py tests/test_approval.py -v
```
Expected: ALL PASS

- [x] **Step 9: Commit**

```bash
git add src/chatcc/channel/compose.py src/chatcc/channel/__init__.py tests/test_compose.py
git commit -m "feat(compose): add compose_conflict_choice and compose_confirmation helpers"
```

### Task 4: 注册 `/resolve` 命令 + app.py 处理

**Files:**
- Modify: `src/chatcc/command/commands.py`
- Modify: `src/chatcc/app.py`
- Modify: `tests/test_app_integration.py`

**设计要点:**
- `/resolve {id} {value}` — 拦截命令，不经过 agent
- `app.py` `_handle_intercept` 新增 `/resolve` 分支: 调 `approval_table.resolve(id, value)`
- 校验: value 必须在对应 item 的 choices 中（如果 choices 不为 None），否则拒绝

- [x] **Step 1: 写 test — /resolve 命令处理**

```python
# tests/test_app_integration.py — 新增

async def test_handle_resolve_choice(app):
    choices = [("排队", "queue"), ("打断", "interrupt"), ("取消", "cancel")]
    future, aid = app.approval_table.request_choice(
        "proj", "send_to_claude", "conflict", choices=choices,
    )
    msg = InboundMessage(sender_id="u1", chat_id="chat-1", content=f"/resolve {aid} queue")
    result = RouteResult(intercepted=True, command="/resolve", args=[str(aid), "queue"])
    await app._handle_intercept(result, msg)

    import asyncio
    resolved = await asyncio.wait_for(future, timeout=1.0)
    assert resolved == "queue"

    outbound = app.channel.send.await_args.args[0]
    assert "queue" in outbound.content or "已选择" in outbound.content


async def test_handle_resolve_invalid_id(app):
    msg = InboundMessage(sender_id="u1", chat_id="chat-1", content="/resolve 999 queue")
    result = RouteResult(intercepted=True, command="/resolve", args=["999", "queue"])
    await app._handle_intercept(result, msg)

    outbound = app.channel.send.await_args.args[0]
    assert "不存在" in outbound.content or "已处理" in outbound.content
```

- [x] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_app_integration.py::test_handle_resolve_choice -v
```
Expected: FAIL

- [x] **Step 3: 注册 `/resolve` 命令**

`src/chatcc/command/commands.py` — 在 `INTERCEPT_COMMANDS` 列表中添加:

```python
CommandSpec(
    name="resolve",
    description="解决待确认选择",
    params=[
        ParamDef("id", required=True, description="待确认项 ID"),
        ParamDef("value", required=True, description="选择的值"),
    ],
    route_type=RouteType.INTERCEPT,
    category="审批",
),
```

- [x] **Step 4: app.py 添加 `/resolve` 处理**

在 `_handle_intercept` 的 `match command:` 中，在 `/pending` 之前添加:

```python
case "/resolve":
    if len(args) < 2:
        response = "用法: /resolve <id> <value>"
    else:
        try:
            aid = int(args[0])
            value = args[1]
            entry = self.approval_table._pending.get(aid)
            if entry and entry.choices and value not in [v for _, v in entry.choices]:
                valid = ", ".join(v for _, v in entry.choices)
                response = f"无效选择 '{value}'，可选: {valid}"
            elif self.approval_table.resolve(aid, value):
                response = f"已选择: {value} (#{aid})"
            else:
                response = f"#{aid} 不存在或已处理"
        except ValueError:
            response = f"无效的 ID: {args[0]}"
```

**注意:** 访问 `_pending` 是内部实现细节。更好的方式是给 `ApprovalTable` 加一个 `get_pending(id)` 公开方法。

- [x] **Step 5: ApprovalTable 加 `get_pending()` 方法**

```python
# src/chatcc/approval/table.py

def get_pending(self, approval_id: int) -> PendingApproval | None:
    return self._pending.get(approval_id)
```

然后 app.py 用 `self.approval_table.get_pending(aid)` 替代 `self.approval_table._pending.get(aid)`。

- [x] **Step 6: 运行测试**

```bash
pytest tests/test_app_integration.py tests/test_approval.py -v
```
Expected: ALL PASS

- [x] **Step 7: Commit**

```bash
git add src/chatcc/command/commands.py src/chatcc/app.py src/chatcc/approval/table.py tests/test_app_integration.py
git commit -m "feat(commands): add /resolve intercept command for multi-choice approval"
```

---

## Chunk 3: session.py 适配 + 主 Agent Tools 内联确认

### Task 5: session.py _permission_handler 适配 Future[str]

**Files:**
- Modify: `src/chatcc/claude/session.py`

**设计要点:**
- `allowed = await future` 原来返回 `bool`，现在返回 `str`
- 改为: `result = await future; allowed = (result == "approve")`
- 一行改动，但关键路径

- [x] **Step 1: 修改 _permission_handler**

`src/chatcc/claude/session.py` 第 229 行:

```python
# Before:
allowed = await future

# After:
result = await future
allowed = result == "approve"
```

- [x] **Step 2: 运行现有测试**

```bash
pytest tests/ -v --timeout=10
```
Expected: ALL PASS

- [x] **Step 3: Commit**

```bash
git add src/chatcc/claude/session.py
git commit -m "fix(session): adapt _permission_handler to Future[str] approval result"
```

### Task 6: send_to_claude 内联 conflict 确认

**Files:**
- Modify: `src/chatcc/tools/session_tools.py`

**设计要点:**
- 当 `submit_task` 返回 `status == "conflict"` 且没有 `on_conflict` 策略时:
  1. 调用 `approval_table.request_choice(...)` 创建选择项
  2. 通过 `send_fn` 发送 `compose_conflict_choice` 卡片
  3. `await future` 等待用户选择
  4. 根据选择执行 queue/interrupt/cancel
- 如果 `approval_table` 或 `send_fn` 不可用，退回原有行为（返回文本让 agent 问用户）
- `on_conflict` 参数仍然有效 — 如果调用方已经带了策略，直接执行

- [x] **Step 1: 写 test — send_to_claude conflict 发送卡片并 await**

这个需要在一个集成式 test 中模拟:
1. 创建一个正在运行任务的 mock TaskManager
2. 调用 send_to_claude → 触发 conflict
3. 验证 send_fn 被调用发送了 RichMessage
4. resolve future
5. 验证后续操作

由于 pydantic-ai tool 测试较复杂，可以直接 mock `send_to_claude` 的内部逻辑做单元测试。

```python
# tests/test_session_tools_confirm.py

import asyncio
from unittest.mock import AsyncMock, MagicMock
from chatcc.approval.table import ApprovalTable
from chatcc.channel.message import OutboundMessage, RichMessage


async def test_send_to_claude_conflict_sends_choice_card():
    """When conflict occurs and no on_conflict given,
    tool should send an interactive card and await user choice."""
    table = ApprovalTable()
    sent_messages: list[OutboundMessage] = []

    async def mock_send(msg: OutboundMessage):
        sent_messages.append(msg)

    # Simulate: resolve the choice after card is sent
    async def auto_resolve():
        while table.pending_count == 0:
            await asyncio.sleep(0.01)
        items = table.list_pending()
        table.resolve(items[0].id, "queue")

    resolve_task = asyncio.create_task(auto_resolve())

    # Call the helper function that will be extracted
    from chatcc.tools._confirm import confirm_conflict

    result = await confirm_conflict(
        table=table,
        send_fn=mock_send,
        chat_id="chat-1",
        project="myapp",
        prompt="build feature",
    )

    assert result == "queue"
    assert len(sent_messages) == 1
    assert isinstance(sent_messages[0].content, RichMessage)
    await resolve_task
```

- [x] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_session_tools_confirm.py -v
```
Expected: FAIL — `chatcc.tools._confirm` 不存在

- [x] **Step 3: 创建 confirm helper 模块**

提取确认逻辑到一个可测试的 helper 中，避免 pydantic-ai tool 内部代码过于复杂。

`src/chatcc/tools/_confirm.py`:

```python
"""Inline confirmation helpers for main-agent tools.

These functions encapsulate the pattern:
  request choice → send card → await future → return user's choice.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from chatcc.approval.table import ApprovalTable
from chatcc.channel.compose import compose_conflict_choice, compose_confirmation
from chatcc.channel.message import OutboundMessage, RichMessage


async def confirm_conflict(
    table: ApprovalTable,
    send_fn: Callable[[OutboundMessage], Awaitable[None]],
    chat_id: str,
    project: str,
    prompt: str,
) -> str:
    """Present queue/interrupt/cancel choice and return the user's pick."""
    choices = [
        ("📋 排队等待", "queue"),
        ("⚡ 打断执行", "interrupt"),
        ("❌ 取消", "cancel"),
    ]
    future, aid = table.request_choice(
        project=project,
        tool_name="send_to_claude",
        input_summary=f"任务冲突: {prompt[:100]}",
        choices=choices,
    )
    msg = compose_conflict_choice(project, prompt, aid)
    await send_fn(OutboundMessage(chat_id=chat_id, content=msg))
    return await future


async def confirm_action(
    table: ApprovalTable,
    send_fn: Callable[[OutboundMessage], Awaitable[None]],
    chat_id: str,
    project: str,
    description: str,
) -> bool:
    """Present approve/deny confirmation and return True if approved."""
    future, aid = table.request_approval(
        project=project,
        tool_name="confirm",
        input_summary=description,
    )
    msg = compose_confirmation(project, description, aid)
    await send_fn(OutboundMessage(chat_id=chat_id, content=msg))
    result = await future
    return result == "approve"
```

- [x] **Step 4: 运行 confirm helper 测试**

```bash
pytest tests/test_session_tools_confirm.py -v
```
Expected: PASS

- [x] **Step 5: 更新 send_to_claude tool**

`src/chatcc/tools/session_tools.py` — 修改 `send_to_claude`:

```python
@agent.tool
async def send_to_claude(
    ctx: RunContext[Any],
    prompt: str,
    project: str = "",
    on_conflict: str = "",
) -> str:
    """将开发指令发送到目标项目的 Claude Code 会话。

    当项目正在执行任务时 submit_task 会返回 conflict 状态。如果界面支持
    交互按钮，系统会自动发送选择卡片让用户点选；否则你**必须**询问用户
    选择策略，然后用 on_conflict 参数重新调用本工具：
      - "queue"     — 排队等待当前任务完成后执行
      - "interrupt" — 中断当前任务，优先执行新任务
      - "cancel"    — 取消本次提交
    """
    tm = ctx.deps.task_manager
    pm = ctx.deps.project_manager
    if not tm:
        return "错误: 任务管理器未初始化"
    if not pm:
        return "错误: 项目管理器未初始化"

    proj_name = _resolve_project_name(pm, project)
    if not proj_name:
        return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

    result = await tm.submit_task(proj_name, prompt)

    if result.status == "conflict":
        if on_conflict == "queue":
            result = await tm.enqueue_task(proj_name, prompt)
            return result.message
        elif on_conflict == "interrupt":
            result = await tm.interrupt_and_submit(proj_name, prompt)
            return result.message
        elif on_conflict == "cancel":
            return "已取消提交"

        # No strategy — try inline confirmation
        table = ctx.deps.approval_table
        send_fn = ctx.deps.send_fn
        if table and send_fn and ctx.deps.chat_id:
            from chatcc.tools._confirm import confirm_conflict

            choice = await confirm_conflict(
                table=table,
                send_fn=send_fn,
                chat_id=ctx.deps.chat_id,
                project=proj_name,
                prompt=prompt,
            )
            if choice == "queue":
                result = await tm.enqueue_task(proj_name, prompt)
                return result.message
            elif choice == "interrupt":
                result = await tm.interrupt_and_submit(proj_name, prompt)
                return result.message
            else:
                return "已取消提交"

        return result.message

    return result.message
```

- [x] **Step 6: 运行所有测试**

```bash
pytest tests/ -v --timeout=10
```
Expected: ALL PASS

- [x] **Step 7: Commit**

```bash
git add src/chatcc/tools/_confirm.py src/chatcc/tools/session_tools.py tests/test_session_tools_confirm.py
git commit -m "feat(tools): inline conflict confirmation for send_to_claude via ApprovalTable"
```

### Task 7: interrupt_task 加确认

**Files:**
- Modify: `src/chatcc/tools/session_tools.py`
- Modify: `tests/test_session_tools_confirm.py`

- [x] **Step 1: 写 test — confirm_action helper**

```python
# tests/test_session_tools_confirm.py — 新增

async def test_confirm_action_approved():
    table = ApprovalTable()
    sent: list[OutboundMessage] = []

    async def mock_send(msg: OutboundMessage):
        sent.append(msg)

    async def auto_approve():
        while table.pending_count == 0:
            await asyncio.sleep(0.01)
        items = table.list_pending()
        table.resolve(items[0].id, "approve")

    task = asyncio.create_task(auto_approve())
    from chatcc.tools._confirm import confirm_action

    result = await confirm_action(
        table=table, send_fn=mock_send, chat_id="c1",
        project="proj", description="确定要中断任务？",
    )
    assert result is True
    await task


async def test_confirm_action_denied():
    table = ApprovalTable()
    sent: list[OutboundMessage] = []

    async def mock_send(msg: OutboundMessage):
        sent.append(msg)

    async def auto_deny():
        while table.pending_count == 0:
            await asyncio.sleep(0.01)
        items = table.list_pending()
        table.resolve(items[0].id, "deny")

    task = asyncio.create_task(auto_deny())
    from chatcc.tools._confirm import confirm_action

    result = await confirm_action(
        table=table, send_fn=mock_send, chat_id="c1",
        project="proj", description="确定要中断任务？",
    )
    assert result is False
    await task
```

- [x] **Step 2: 运行测试确认通过** (confirm_action 已在 Step 3 of Task 6 中实现)

```bash
pytest tests/test_session_tools_confirm.py -v
```
Expected: ALL PASS

- [x] **Step 3: 更新 interrupt_task tool**

```python
@agent.tool
async def interrupt_task(ctx: RunContext[Any], project: str = "") -> str:
    """中断项目当前正在执行的 Claude Code 任务"""
    tm = ctx.deps.task_manager
    pm = ctx.deps.project_manager
    if not tm or not pm:
        return "错误: 管理器未初始化"

    proj_name = _resolve_project_name(pm, project)
    if not proj_name:
        return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

    # Inline confirmation if infrastructure available
    table = ctx.deps.approval_table
    send_fn = ctx.deps.send_fn
    if table and send_fn and ctx.deps.chat_id:
        from chatcc.tools._confirm import confirm_action

        approved = await confirm_action(
            table=table,
            send_fn=send_fn,
            chat_id=ctx.deps.chat_id,
            project=proj_name,
            description=f"确定要中断项目 [{proj_name}] 当前正在执行的任务？",
        )
        if not approved:
            return "已取消中断操作"

    return await tm.interrupt_task(proj_name)
```

- [x] **Step 4: 运行所有测试**

```bash
pytest tests/ -v --timeout=10
```
Expected: ALL PASS

- [x] **Step 5: Commit**

```bash
git add src/chatcc/tools/session_tools.py tests/test_session_tools_confirm.py
git commit -m "feat(tools): add confirmation step to interrupt_task"
```

---

## Chunk 4: 收尾 — 全面测试 + 边界情况

### Task 8: 边界情况处理

**Files:**
- Modify: `src/chatcc/tools/_confirm.py` (超时)
- Modify: `tests/test_session_tools_confirm.py`

**设计要点:**
- 如果 `send_fn` 调用失败，清理 pending 项并退回文本模式
- 考虑添加超时: 如果用户长时间不响应，auto-cancel (可选，先不实现，留接口)

- [x] **Step 1: 写 test — send_fn 异常时的回退**

```python
async def test_confirm_conflict_send_fails_fallback():
    """If send_fn raises, the pending item should be cleaned up."""
    table = ApprovalTable()

    async def bad_send(msg):
        raise ConnectionError("channel down")

    from chatcc.tools._confirm import confirm_conflict

    # Should not hang — should raise or return a fallback
    try:
        result = await asyncio.wait_for(
            confirm_conflict(
                table=table, send_fn=bad_send, chat_id="c",
                project="p", prompt="x",
            ),
            timeout=2.0,
        )
        assert result == "cancel"  # fallback to cancel
    except ConnectionError:
        pass  # also acceptable
    assert table.pending_count == 0  # cleaned up
```

- [x] **Step 2: 更新 _confirm.py — 异常处理**

```python
async def confirm_conflict(...) -> str:
    choices = [...]
    future, aid = table.request_choice(...)
    try:
        msg = compose_conflict_choice(project, prompt, aid)
        await send_fn(OutboundMessage(chat_id=chat_id, content=msg))
    except Exception:
        table.resolve(aid, "cancel")
        return "cancel"
    return await future
```

对 `confirm_action` 做同样处理:

```python
async def confirm_action(...) -> bool:
    future, aid = table.request_approval(...)
    try:
        msg = compose_confirmation(project, description, aid)
        await send_fn(OutboundMessage(chat_id=chat_id, content=msg))
    except Exception:
        table.resolve(aid, "deny")
        return False
    result = await future
    return result == "approve"
```

- [x] **Step 3: 运行测试**

```bash
pytest tests/ -v --timeout=10
```
Expected: ALL PASS

- [x] **Step 4: Commit**

```bash
git add src/chatcc/tools/_confirm.py tests/test_session_tools_confirm.py
git commit -m "fix(confirm): handle send_fn failure with cleanup and fallback"
```

### Task 9: 全量回归测试

- [x] **Step 1: 运行全部测试**

```bash
pytest tests/ -v --timeout=30
```
Expected: ALL PASS

- [x] **Step 2: 如有失败，修复**

常见问题:
- `test_app_integration.py` 中的旧测试可能用 `result is True` / `result is False` 断言 — 需改为 `== "approve"` / `== "deny"`
- 飞书渲染测试（如有）可能需要更新

- [x] **Step 3: 最终 commit**

```bash
git add -A
git commit -m "test: update all tests for generalized approval table"
```

---

## 边界情况清单

| 场景 | 处理方式 |
|------|---------|
| 用户点了 `/resolve {id} {invalid_value}` | app.py 校验 value 在 choices 中，返回错误 |
| `/y all` 时混有 choice 项 | `approve_all` 只处理 `is_binary` 的项，跳过 choice |
| `send_fn` 异常（channel 断连） | catch 后 resolve cancel，退回文本模式 |
| agent tool await 期间又收到新消息 | event loop 正常处理，`_on_message` 独立于 agent `run()` |
| 用户同时触发多个 conflict | 每个有独立 approval_id，互不影响 |
| `approval_table` 或 `send_fn` 不可用 | 退回原有行为（返回文本让 agent 转述） |
| `/resolve` 命令的 id 已被处理 | `resolve()` 返回 False，回复"已处理" |
| PendingApproval.choices 为 None 时调 `/resolve` | `resolve()` 正常工作（不校验 choices） — app.py 层做校验 |
