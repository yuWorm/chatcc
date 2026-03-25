# P3 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 P0-P2 的各模块骨架串联成可运行的完整系统。补齐 Agent 工具集、Application 全量集成、多项目并发、服务管理、工具安装、会话压缩。

**Architecture:** 在现有骨架基础上，核心工作是 **向上整合** (将已有模块注入 Application/Dispatcher) 和 **向外扩展** (新增服务管理、工具安装等功能模块)。

**当前状态分析:**

| 组件 | P0-P2 状态 | P3 需要做什么 |
|------|-----------|-------------|
| `Dispatcher` | 只有 2 个 stub 工具 | 注册全部 Agent 工具 (项目/会话/命令/服务/安装) |
| `Application` | 命令处理为 stub，不集成子模块 | 接入 ProjectManager, ApprovalTable, CostTracker, Memory |
| `ProjectSession` | 基础骨架，无 response 消费 | 完善 response 消费 + Hook 事件转发 + 结果通知 |
| 多项目并发 | 不存在 | 新增 TaskManager + SessionProjectMap |
| 服务管理 | 不存在 | 新增 ServiceManager (start/stop/logs) |
| 工具安装 | 不存在 | 新增 install_skill / install_mcp |
| 会话压缩 | History 有 truncate，无自动触发 | 新增 SummaryManager + 自动压缩逻辑 |

**Tech Stack:** 无新依赖，使用现有 pydantic-ai + claude-agent-sdk + asyncio。

---

## Chunk 1: Agent 工具集完善

> Dispatcher 当前只注册了 `send_message` 和 `get_status` 两个 stub 工具。
> 架构文档定义了 6 类工具共 15+ 个。此 Chunk 将 AgentDeps 改造为完整上下文，注册全部工具。

### Task 1: 重构 AgentDeps 为完整运行时上下文

**Files:**
- Modify: `src/chatcc/agent/dispatcher.py`
- Create: `tests/test_dispatcher_tools.py`

**设计:** AgentDeps 从简单 dataclass 改为持有所有子模块的引用，供工具函数通过 `RunContext` 访问:

```python
@dataclass
class AgentDeps:
    project_manager: ProjectManager
    approval_table: ApprovalTable
    cost_tracker: CostTracker
    history: ConversationHistory
    longterm_memory: LongTermMemory
    task_manager: TaskManager          # Chunk 3 新增
    service_manager: ServiceManager    # Chunk 4 新增
    send_fn: Callable[[OutboundMessage], Awaitable[None]]
    chat_id: str                       # 当前消息来源
```

- [ ] **Step 1: 写工具注册测试** — 验证 Dispatcher 注册了预期工具名
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 重构 AgentDeps** — 添加所有子模块引用，保持可选 (初始部分为 None)
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `refactor: expand AgentDeps to hold all subsystem references`

---

### Task 2: 注册项目管理工具

**Files:**
- Create: `src/chatcc/tools/__init__.py`
- Create: `src/chatcc/tools/project_tools.py`
- Create: `tests/test_tools_project.py`

工具列表 (全部通过 `RunContext[AgentDeps]` 访问 `project_manager`):

| 工具 | 参数 | 行为 |
|------|------|------|
| `create_project` | name: str, path: str | 调用 pm.create_project，返回确认 |
| `list_projects` | 无 | 返回项目列表 + 默认标记 |
| `switch_project` | name: str | 切换默认项目 |
| `get_project_info` | name: str \| None | 查看指定/默认项目详情 |
| `delete_project` | name: str | 归档项目 |

**实现模式:** 工具函数定义在独立模块，由 Dispatcher 导入注册:

```python
# tools/project_tools.py
def register_project_tools(agent: Agent):
    @agent.tool
    def create_project(ctx: RunContext[AgentDeps], name: str, path: str) -> str:
        project = ctx.deps.project_manager.create_project(name, path)
        return f"项目 '{name}' 创建成功 (路径: {path})"
    # ...
```

- [ ] **Step 1: 写工具函数测试** — mock ProjectManager，验证每个工具返回值
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 project_tools.py**
- [ ] **Step 4: 在 Dispatcher 中调用 `register_project_tools(self.agent)`**
- [ ] **Step 5: 运行测试确认通过**
- [ ] **Step 6: Commit** — `feat: add project management tools for main agent`

---

### Task 3: 注册 Claude Code 会话工具

**Files:**
- Create: `src/chatcc/tools/session_tools.py`
- Create: `tests/test_tools_session.py`

| 工具 | 参数 | 行为 |
|------|------|------|
| `send_to_claude` | prompt: str, project: str \| None | 向目标项目 Claude Code 发送指令，异步执行 |
| `list_sessions` | project: str \| None | 列出会话 (调用 claude_agent_sdk.list_sessions) |
| `switch_session` | session_id: str, project: str \| None | resume 指定会话 |
| `new_session` | project: str \| None | 归档旧会话，创建新 client |

`send_to_claude` 是核心工具 — 将用户的开发指令下发到 Claude Code。它需要:
1. 通过 `task_manager` 定位目标项目的 `ProjectSession`
2. 调用 `session.send_task(prompt)` 异步执行
3. 启动后台 `asyncio.Task` 消费 `receive_response()`，将结果/通知转发回 IM

- [ ] **Step 1: 写会话工具测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 session_tools.py**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: add Claude Code session tools for main agent`

---

### Task 4: 注册命令执行工具

**Files:**
- Create: `src/chatcc/tools/command_tools.py`
- Create: `tests/test_tools_command.py`

| 工具 | 参数 | 行为 |
|------|------|------|
| `execute_command` | command: str, project: str \| None | 在项目目录执行 shell 命令，返回 stdout/stderr |

安全约束:
- 使用 `validate_workspace_boundary()` 校验 cwd 路径
- 使用 `asyncio.create_subprocess_exec` 异步执行
- 设置 timeout (默认 30s)
- 捕获 stdout + stderr 返回给 Agent

- [ ] **Step 1: 写命令执行测试** — 测试正常命令、路径逃逸拒绝、超时
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 command_tools.py**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: add command execution tool with workspace boundary check`

---

## Chunk 2: Application 全量集成

> 将 P0-P2 的所有子模块注入 Application，实现完整的消息处理流程。

### Task 5: Application 子模块初始化

**Files:**
- Modify: `src/chatcc/app.py`
- Create: `tests/test_app.py`

Application 初始化链:

```python
class Application:
    def __init__(self, config):
        self.config = config
        self.project_manager = ProjectManager(...)
        self.approval_table = ApprovalTable()
        self.cost_tracker = CostTracker(budget_limit=config.budget.daily_limit)
        self.history = ConversationHistory(storage_dir=CHATCC_HOME / "history")
        self.longterm_memory = LongTermMemory(memory_dir=CHATCC_HOME / "memory")
        self.task_manager = TaskManager(...)  # Chunk 3
        self.router = MessageRouter()
        self.channel = None
        self.dispatcher = None
```

- [ ] **Step 1: 写 Application 初始化测试** — 验证各子模块创建、依赖注入
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 重构 Application.__init__** — 初始化全部子模块
- [ ] **Step 4: 重构 _init_dispatcher** — 传入完整 AgentDeps 工厂
- [ ] **Step 5: 运行测试确认通过**
- [ ] **Step 6: Commit** — `refactor: wire all subsystems into Application`

---

### Task 6: 实现快捷命令处理

**Files:**
- Modify: `src/chatcc/app.py`
- Create: `tests/test_app_commands.py`

将 `_handle_command` 从 stub 改为真正操作:

```python
async def _handle_command(self, command, args, message):
    match command:
        case "/y":
            if args and args[0] == "all":
                count = self.approval_table.approve_all()
                response = f"已全部确认 ({count} 条)"
            elif args:
                self.approval_table.approve(int(args[0]))
                response = f"已确认 #{args[0]}"
            else:
                self.approval_table.approve_oldest()
                response = "已确认最早待审批项"
        case "/n":
            # 类似 /y 的逻辑
        case "/pending":
            pending = self.approval_table.list_pending()
            # 格式化为 RichMessage
        case "/stop":
            # 找到当前项目的 ProjectSession，调用 interrupt()
        case "/status":
            # 汇总: 项目数、活跃任务、待审批、费用
```

- [ ] **Step 1: 写命令处理测试** — 模拟各命令场景
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现完整命令处理**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: implement shortcut command handlers (/y /n /pending /stop /status)`

---

### Task 7: Agent 消息处理集成 history + memory

**Files:**
- Modify: `src/chatcc/app.py`

完善 `_handle_agent_message`:
1. 将用户消息写入 `ConversationHistory`
2. 构建 AgentDeps 时注入真实状态
3. 将 message_history 传入 `agent.run()` (pydantic-ai 支持 message_history 参数)
4. 将 Agent 响应写入 `ConversationHistory`
5. 检查是否需要触发会话压缩 (Chunk 5)

- [ ] **Step 1: 写集成测试**
- [ ] **Step 2: 实现完整消息处理链**
- [ ] **Step 3: 运行测试确认通过**
- [ ] **Step 4: Commit** — `feat: integrate conversation history and memory into agent message flow`

---

## Chunk 3: 多项目并发

> 当前 Application 没有 TaskManager，无法管理多项目的 ProjectSession 生命周期。

### Task 8: TaskManager

**Files:**
- Create: `src/chatcc/claude/task_manager.py`
- Create: `tests/test_task_manager.py`

```python
class TaskManager:
    """管理所有项目的 ProjectSession 生命周期"""
    
    def __init__(self, project_manager, approval_table, on_notify):
        self._sessions: dict[str, ProjectSession] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._session_project_map = SessionProjectMap()
    
    def get_session(self, project_name) -> ProjectSession:
        """获取或创建项目的 session"""
    
    async def submit_task(self, project_name, prompt) -> None:
        """向项目提交开发任务 (同一项目内串行)"""
    
    async def interrupt_task(self, project_name) -> None:
        """中断项目当前任务"""
    
    def get_status(self, project_name) -> TaskState:
        """查询项目任务状态"""
```

**并发模型:**
- 每个项目维护独立的 `ProjectSession` 和 `asyncio.Task`
- 同一项目串行: submit_task 如果项目 RUNNING，排队等待 (或拒绝)
- 跨项目并行: 不同项目的 asyncio.Task 独立运行

- [ ] **Step 1: 写 TaskManager 测试** — 单项目提交/中断、多项目并行场景
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 TaskManager**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: add TaskManager for multi-project concurrent execution`

---

### Task 9: SessionProjectMap + Hook 事件转发

**Files:**
- Create: `src/chatcc/claude/events.py`
- Modify: `src/chatcc/claude/session.py`
- Create: `tests/test_events.py`

```python
class SessionProjectMap:
    """session_id → project_name 映射"""
    def register(self, session_id, project_name): ...
    def get_project(self, session_id) -> str | None: ...
```

完善 ProjectSession 的 response 消费:

```python
async def consume_response(self) -> ResultMessage:
    """消费 Claude Code 响应直到 ResultMessage"""
    async for message in self.client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    # 转发到 IM
                    await self._on_notification(self.project.name, block.text)
        if isinstance(message, ResultMessage):
            self.task_state = TaskState.COMPLETED
            return message
```

- [ ] **Step 1: 写事件处理测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 SessionProjectMap 和 consume_response**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: add SessionProjectMap and response consumption with IM forwarding`

---

### Task 10: 安全审批 Hook 集成

**Files:**
- Modify: `src/chatcc/claude/session.py`
- Modify: `src/chatcc/claude/task_manager.py`
- Create: `tests/test_approval_integration.py`

将 `assess_risk` + `ApprovalTable` 接入 ProjectSession 的 `can_use_tool` 回调:

```python
async def _permission_handler(self, tool_name, input_data, context):
    risk = assess_risk(tool_name, input_data, workspace=self.project.path)
    match risk:
        case "safe":
            return PermissionResultAllow(updated_input=input_data)
        case "forbidden":
            return PermissionResultDeny(reason="操作超出项目目录")
        case "dangerous":
            # 发送确认消息到 IM
            summary = f"{tool_name}: {_summarize_input(input_data)}"
            future = self._approval_table.request_approval(
                self.project.name, tool_name, summary
            )
            await self._notify_approval_request(summary)
            # 阻塞等待用户确认 (Claude Code 不会超时)
            allowed = await future
            if allowed:
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(reason="用户拒绝")
```

- [ ] **Step 1: 写审批集成测试** — 模拟 safe/dangerous/forbidden 场景
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现完整审批 Hook**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: integrate risk assessment and approval flow into Claude session hooks`

---

## Chunk 4: 服务管理

### Task 11: ServiceManager

**Files:**
- Create: `src/chatcc/service/__init__.py`
- Create: `src/chatcc/service/manager.py`
- Create: `tests/test_service.py`

```python
@dataclass
class RunningService:
    name: str
    project: str
    pid: int
    command: str
    started_at: datetime
    log_file: Path

class ServiceManager:
    async def start(self, project, name, command) -> RunningService:
        """在项目目录启动后台进程"""
    
    async def stop(self, project, name) -> bool:
        """停止服务 (SIGTERM → 等待 → SIGKILL)"""
    
    def status(self, project=None) -> list[RunningService]:
        """查看运行中的服务"""
    
    async def logs(self, project, name, lines=50) -> str:
        """读取服务日志最近 N 行"""
```

实现要点:
- 使用 `asyncio.create_subprocess_exec` 启动
- stdout/stderr 重定向到日志文件 (`~/.chatcc/services/<project>/<name>.log`)
- PID 记录到内存 + 持久化文件，重启后可恢复
- stop 先 SIGTERM，3秒后 SIGKILL

- [ ] **Step 1: 写 ServiceManager 测试** — start/stop/status/logs
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 ServiceManager**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: add ServiceManager for background service lifecycle`

---

### Task 12: 注册服务管理工具

**Files:**
- Create: `src/chatcc/tools/service_tools.py`
- Create: `tests/test_tools_service.py`

| 工具 | 参数 | 行为 |
|------|------|------|
| `start_service` | name: str, command: str, project: str \| None | 启动后台服务 |
| `stop_service` | name: str, project: str \| None | 停止服务 |
| `service_status` | project: str \| None | 列出运行中的服务 |
| `service_logs` | name: str, lines: int = 50, project: str \| None | 查看日志 |

- [ ] **Step 1: 写服务工具测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 service_tools.py**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: add service management tools for main agent`

---

## Chunk 5: 工具安装

### Task 13: 工具安装模块

**Files:**
- Create: `src/chatcc/tools/install_tools.py`
- Create: `tests/test_tools_install.py`

| 工具 | 参数 | 行为 |
|------|------|------|
| `install_skill` | skill_url: str, project: str \| None | 为 Claude Code 安装 skill (写入项目 .claude/ 目录) |
| `install_mcp` | name: str, config: dict, project: str \| None | 为 Claude Code 配置 MCP server |

`install_skill` 实现:
```python
async def install_skill(ctx, skill_url: str, project: str | None) -> str:
    session = ctx.deps.task_manager.get_session(project_name)
    client = await session.ensure_connected()
    # 通过 client.add_mcp_server 或直接写入配置文件
    # 或者通过 send_task 让 Claude Code 自己安装
```

`install_mcp` 实现:
```python
async def install_mcp(ctx, name: str, config: dict, project: str | None) -> str:
    session = ctx.deps.task_manager.get_session(project_name)
    client = await session.ensure_connected()
    mcp_config = McpServerConfig(command=config["command"], args=config.get("args", []))
    await client.add_mcp_server(name, mcp_config)
    return f"MCP server '{name}' 已添加到项目"
```

- [ ] **Step 1: 写安装工具测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 install_tools.py**
- [ ] **Step 4: 运行测试确认通过**
- [ ] **Step 5: Commit** — `feat: add skill and MCP installation tools`

---

## Chunk 6: 会话压缩

### Task 14: SummaryManager

**Files:**
- Create: `src/chatcc/memory/summary.py`
- Create: `tests/test_summary.py`

```python
class SummaryManager:
    def __init__(self, history, longterm_memory, agent_model, config):
        self.threshold_messages = config.get("summarize_threshold", 50)
        self.threshold_token_pct = config.get("summarize_token_percent", 75)
    
    def should_compress(self) -> bool:
        """检查是否需要压缩"""
        return self.history.message_count > self.threshold_messages
    
    async def compress(self) -> str:
        """执行压缩: 保留最近 N 条，旧消息生成摘要，提取事实到长期记忆"""
        old_messages = self.history.truncate(keep_recent=10)
        
        # 用 LLM 生成摘要
        summary = await self._generate_summary(old_messages)
        
        # 提取重要事实到长期记忆
        facts = await self._extract_facts(old_messages)
        if facts:
            self.longterm_memory.append_daily_note(facts)
        
        return summary
```

压缩触发时机:
- 每次 `_handle_agent_message` 处理完后异步检查
- 如果 `should_compress()` 为真，启动压缩

- [ ] **Step 1: 写 SummaryManager 测试**
- [ ] **Step 2: 运行测试确认失败**
- [ ] **Step 3: 实现 SummaryManager**
- [ ] **Step 4: 集成到 Application 的消息处理链**
- [ ] **Step 5: 运行测试确认通过**
- [ ] **Step 6: Commit** — `feat: add session compression with LLM summarization`

---

## Chunk 7: 端到端集成 + CLI auth 完善

### Task 15: CLI auth 命令实现

**Files:**
- Modify: `src/chatcc/main.py`

```python
@cli.command()
@click.option("--channel", default=None)
def auth(channel: str | None):
    config = load_config()
    ch_type = channel or config.channel.type
    ch_config = getattr(config.channel, ch_type, {})
    
    match ch_type:
        case "telegram":
            token = click.prompt("请输入 Telegram Bot Token")
            # 验证 token (调用 getMe)
            # 写入 config.yaml
        case "feishu":
            app_id = click.prompt("请输入飞书 App ID")
            app_secret = click.prompt("请输入飞书 App Secret")
            # 验证凭证
            # 写入 config.yaml
        case "cli":
            click.echo("CLI 渠道无需认证")
```

- [ ] **Step 1: 实现 auth 命令** — 交互式输入 + 验证 + 写入配置
- [ ] **Step 2: 手动测试 `chatcc auth --channel telegram`**
- [ ] **Step 3: Commit** — `feat: implement chatcc auth command for Telegram and Feishu`

---

### Task 16: 端到端启动验证

- [ ] **Step 1: 创建测试配置** — `~/.chatcc/config.yaml` with CLI channel
- [ ] **Step 2: `chatcc run --debug`** — 验证启动、接收消息、Agent 响应、命令拦截
- [ ] **Step 3: 配置 Telegram** — `chatcc auth --channel telegram`，切换 config type，验证 TG 消息收发
- [ ] **Step 4: 配置飞书** — `chatcc auth --channel feishu`，切换 config type，验证飞书消息收发
- [ ] **Step 5: 创建项目** — 通过 IM 对话创建项目，验证 ProjectManager 工作
- [ ] **Step 6: Claude Code 交互** — 发送开发指令，验证 ClaudeSDKClient 启动、任务执行、结果回传
- [ ] **Step 7: Commit** — `feat: end-to-end integration verified`

---

### Task 17: 全量测试

- [ ] **Step 1: 运行全量测试** — `uv run pytest tests/ -v`
- [ ] **Step 2: 检查测试覆盖** — 确保新增模块测试覆盖率 > 80%
- [ ] **Step 3: Lint 检查** — `uv run ruff check src/chatcc/`
- [ ] **Step 4: Final commit** — `chore: P3 implementation complete`

---

## 实现顺序与依赖关系

```
Chunk 1 (Agent Tools)          独立，无依赖
    ├── Task 1: AgentDeps 重构
    ├── Task 2: 项目管理工具
    ├── Task 3: Claude 会话工具  ← 依赖 Chunk 3 的 TaskManager
    └── Task 4: 命令执行工具

Chunk 2 (App Integration)      依赖 Chunk 1
    ├── Task 5: App 子模块初始化
    ├── Task 6: 快捷命令处理
    └── Task 7: Agent 消息集成

Chunk 3 (Multi-project)        可与 Chunk 1 部分并行
    ├── Task 8: TaskManager
    ├── Task 9: SessionProjectMap + response 消费
    └── Task 10: 审批 Hook 集成

Chunk 4 (Service Mgmt)         独立，无依赖
    ├── Task 11: ServiceManager
    └── Task 12: 服务管理工具

Chunk 5 (Tool Install)         依赖 Chunk 3 (需要 TaskManager)
    └── Task 13: 安装工具

Chunk 6 (Compression)          依赖 Chunk 2 (需要 App 集成)
    └── Task 14: SummaryManager

Chunk 7 (E2E)                  依赖全部
    ├── Task 15: CLI auth
    ├── Task 16: E2E 验证
    └── Task 17: 全量测试
```

**推荐执行顺序:**
1. Chunk 1 (Task 1-2, 4) + Chunk 4 (Task 11-12) — 可并行
2. Chunk 3 (Task 8-10)
3. Chunk 1 (Task 3) — 依赖 TaskManager
4. Chunk 2 (Task 5-7)
5. Chunk 5 (Task 13)
6. Chunk 6 (Task 14)
7. Chunk 7 (Task 15-17)

---

## 预期结构新增/修改

```
src/chatcc/
├── tools/                      # [新增] 主 Agent 工具集
│   ├── __init__.py
│   ├── project_tools.py        # 项目管理工具
│   ├── session_tools.py        # Claude 会话工具
│   ├── command_tools.py        # 命令执行工具
│   ├── service_tools.py        # 服务管理工具
│   └── install_tools.py        # 工具安装 (skill/mcp)
│
├── service/                    # [新增] 服务管理
│   ├── __init__.py
│   └── manager.py              # ServiceManager
│
├── claude/
│   ├── session.py              # [修改] 完善 response 消费 + 审批 Hook
│   ├── task_manager.py         # [新增] TaskManager (多项目并发)
│   └── events.py               # [新增] SessionProjectMap + 事件处理
│
├── memory/
│   ├── summary.py              # [新增] SummaryManager (会话压缩)
│   └── ...
│
├── agent/
│   └── dispatcher.py           # [修改] AgentDeps 重构 + 全部工具注册
│
├── app.py                      # [修改] 全量集成
└── main.py                     # [修改] auth 命令实现
```
