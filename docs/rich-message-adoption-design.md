# RichMessage 落地设计

> 日期: 2026-03-27
> 方案: 渐进式 (Plan C) — 先做确定性高的场景，Agent 回复解析 opt-in

## 背景

`channel/message.py` 定义了完整的富文本类型体系 (`TextElement`, `CodeElement`, `ActionGroup`, `ProgressElement`, `DividerElement`, `RichMessage`)，4 个 channel (CLI / Telegram / Feishu / WeChat) 都实现了 `render()` 方法。但当前没有任何代码实例化这些类型 — 所有消息都以纯 `str` 发送。

## 目标

让 `RichMessage` 在以下 4 个场景中落地：

1. **审批请求** — 危险操作通知带可点击按钮 (Telegram/Feishu)
2. **任务状态通知** — 完成/失败/中断/重试等状态用 `ProgressElement` 展示
3. **命令响应** — `/pending` `/help` 等用结构化富消息
4. **Agent 回复** — Markdown 解析为 `TextElement` + `CodeElement` (opt-in)

## 架构

### 新增模块: `channel/compose.py`

作为 RichMessage 的唯一构造入口。所有需要发富消息的调用方通过这里构建，而不是散落的字符串拼接。

```
channel/compose.py
├── compose_approval(project, tool_name, summary, approval_id) → RichMessage
├── compose_task_completed(project, cost) → RichMessage
├── compose_task_failed(project, error) → RichMessage
├── compose_task_interrupted(project) → RichMessage
├── compose_session_rotated(project, reason) → RichMessage
├── compose_pending_list(pending_items) → RichMessage
├── compose_help(help_text) → RichMessage
└── parse_markdown(text, project?) → RichMessage
```

### 通知回调签名变更

```python
# Before
on_notify: Callable[[str, str], Awaitable[None]]

# After
on_notify: Callable[[str, str | RichMessage], Awaitable[None]]
```

影响链路:
- `TaskManager.__init__` / `_notify()`
- `ProjectSession.__init__` / `_on_notification`
- `Application._on_claude_notify()`

### app.py 适配

`_on_claude_notify` 需要判断 `str | RichMessage`:
- `RichMessage` → 自带 `project_tag`，直接作为 `OutboundMessage.content`
- `str` → 保持现有 `f"[{project_name}] {message}"` 拼接

`_handle_intercept` 中 `/pending` `/help` 改为构造 `RichMessage`。

Agent 回复路径 (`_handle_agent_message` / `_handle_augmented`):
- 新增配置 `rich_message.parse_agent_markdown: bool` (默认 `false`)
- 当开启时，调用 `parse_markdown(response_text)` 转为 `RichMessage`

## 场景详细设计

### 1. 审批请求

当前 (`session.py:223`):
```python
await self._on_notification(
    self.project.name,
    f"⚠️ 危险操作待确认:\n{tool_name}: {summary}\n回复 /y 确认 或 /n 拒绝",
)
```

改为:
```python
from chatcc.channel.compose import compose_approval

msg = compose_approval(self.project.name, tool_name, summary, approval_id)
await self._on_notification(self.project.name, msg)
```

其中 `approval_id` 来自 `self._approval_table.request_approval()` 返回的 future 关联 ID。需要调整 `request_approval()` 使其返回 `(future, id)` 而非只返回 `future`。

平台效果:
- **Telegram**: InlineKeyboardButton `/y {id}` / `/n {id}`
- **Feishu**: 卡片按钮 (primary/danger)
- **WeChat/CLI**: 文本降级 `[✅ 确认] /y {id} | [❌ 拒绝] /n {id}`

### 2. 任务状态通知

`task_manager.py` 中所有 `_notify()` 调用改为 compose 函数:

| 当前文本 | compose 函数 |
|---------|-------------|
| `"✅ 任务完成 (${cost:.4f})"` | `compose_task_completed(project, cost)` |
| `"❌ 任务失败: {exc}"` | `compose_task_failed(project, str(exc))` |
| `"⏸️ 任务已中断"` | `compose_task_interrupted(project)` |
| `"🔄 会话已自动轮转..."` | `compose_session_rotated(project, "...")` |
| `"🔄 会话上下文过长..."` | `compose_session_rotated(project, "上下文过长")` |
| `"🔄 Claude Code 进程异常..."` | `compose_session_rotated(project, "进程异常")` |
| `"✅ 重试成功 (${cost:.4f})"` | `compose_task_completed(project, cost)` |
| `"❌ 重试失败: {exc}"` | `compose_task_failed(project, str(exc))` |

### 3. 命令响应

`/pending`:
```python
RichMessage(elements=[
    TextElement(f"待确认操作 ({len(pending)} 条):"),
    # for each pending:
    TextElement(f"#{p.id} [{p.project}] {p.tool_name}: {p.input_summary}"),
    ActionGroup([ActionButton("✅ 确认", f"/y {p.id}"), ActionButton("❌ 拒绝", f"/n {p.id}")]),
    DividerElement(),
])
```

`/help`: 用 `TextElement` 分段展示命令列表。

### 4. Agent 回复 Markdown 解析

`parse_markdown()` 实现思路:
1. 用正则按 ` ``` ` 代码围栏分割文本
2. 围栏外的文本 → `TextElement`
3. 围栏内的代码 → `CodeElement(code, language)`
4. 空文本段跳过

不做完整 markdown AST 解析 — 只处理代码围栏，其余保留为 TextElement 内的原始 markdown 文本。各 channel 的 render 已经能处理 TextElement 中的 markdown（Feishu 用 `lark_md`，Telegram 用 `parse_mode="Markdown"`）。

配置:
```yaml
rich_message:
  parse_agent_markdown: false  # 默认关闭
```

## 约束与注意事项

- 所有 compose 函数用于 TaskManager / session 路径时 **必须设置 `project_tag`**，以保持与当前 `f"[{project_name}] {message}"` 一致的行为。
- `compose_session_rotated` 的 `reason` 参数仅用于内部区分样式；最终用户可见文本保持与当前一致，不改变现有文案。
- `parse_markdown` 在输入为空或无有效段落时，返回包含单个空 `TextElement` 的 `RichMessage`，而非 fallback 到 `str`。
- Telegram `callback_data` 有 64 字节限制，当前 `/y {id}` / `/n {id}` 格式足够短。
- 配置结构：新增 `RichMessageConfig` dataclass + `load_config` 分支，与 `SessionPolicyConfig` 模式一致。

## Bug 修复

### Feishu 卡片按钮回调未注册

`feishu.py` 的 `start()` 中 `_on_card_action` 未注册到 event handler，导致飞书卡片按钮点击无响应:

```python
# feishu.py start() — 需要新增 card action 注册
event_handler = (
    lark.EventDispatcherHandler.builder("", "")
    .register_p2_im_message_receive_v1(self._on_message_event)
    .register_p2_card_action_trigger(self._on_card_action)  # 新增
    .build()
)
```

> 注意：飞书开发者后台也需要订阅 card action 事件，SDK 注册只是代码侧。

## 改动文件清单

| 文件 | 改动类型 | 描述 |
|------|---------|------|
| `channel/compose.py` | 新增 | compose 函数 + parse_markdown |
| `channel/__init__.py` | 修改 | 导出 compose 函数 |
| `claude/session.py` | 修改 | `_permission_handler` 用 `compose_approval()`；签名变更 |
| `claude/task_manager.py` | 修改 | `_notify` 签名；各状态通知改用 compose |
| `approval/table.py` | 修改 | `request_approval` 返回 `(future, id)` |
| `app.py` | 修改 | `_on_claude_notify` 适配；`_handle_intercept` 富消息；agent 回复 opt-in |
| `channel/feishu.py` | 修改 | 注册 `_on_card_action` |
| `config.py` | 修改 | 新增 `rich_message` 配置段 |

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| Telegram Markdown 特殊字符导致发送失败 | `parse_markdown` 内对 TextElement 内容做 escape |
| 飞书 card action 注册方式不兼容 | 查阅 lark SDK 确认 API |
| 审批 ID 传递需要改 approval_table 接口 | 改动小且局部化 |
| Agent markdown 解析边界 case | opt-in 开关，默认关闭 |
