# Tool-Use Agent 架构设计文档

> 基于 PicoClaw 项目架构提炼的语言无关设计方案，可直接用于其他项目实现。

---

## 一、核心概念

| 概念 | 定义 |
|------|------|
| **Turn** | 一次完整的「用户输入 → LLM 多轮迭代 → 最终响应」循环 |
| **Iteration** | Turn 内的单次 LLM 调用 + 工具执行（一个 Turn 可包含多次 Iteration） |
| **SubTurn** | 工具内部递归生成的子 Turn（形成树状执行结构） |
| **Session** | 一个持久化的对话上下文，包含消息历史 + 摘要 |
| **Steering** | Turn 执行期间用户插入的新消息，不启动新 Turn 而是注入当前 Turn |

---

## 二、Agent Loop 设计

### 2.1 三层循环架构

```
┌─ 第一层: 主事件循环 ───────────────────────────┐
│  while running:                                 │
│    msg = bus.receive()                          │
│    response = processMessage(msg)               │
│    while hasSteeringMessages():                 │
│      response = continue(steeringMsg)           │
│    send(response)                               │
└─────────────────────────────────────────────────┘
         │
         ▼
┌─ 第二层: Turn 迭代循环 ────────────────────────┐
│  for i in 1..maxIterations:                     │
│    injectSteeringMessages()                     │
│    response = callLLM(messages, tools)          │
│    if noToolCalls(response): return response    │
│    for toolCall in response.toolCalls:          │
│      result = executeTool(toolCall)             │
│      messages.append(toolResult)                │
└─────────────────────────────────────────────────┘
         │ (工具内可递归)
         ▼
┌─ 第三层: SubTurn 递归循环 ─────────────────────┐
│  childTurn = spawnSubTurn(task, tools)          │
│  result = runTurn(childCtx, childTurnState)     │
│  return result                                  │
└─────────────────────────────────────────────────┘
```

### 2.2 第一层：主事件循环

**职责**: 从消息总线接收入站消息，分发处理，管理 Steering 队列。

```
主事件循环:
  1. 从 InboundChannel 阻塞读取消息
  2. 启动 Steering 拦截器（并行协程/线程）
     - 读取同 Session 的后续消息 → 放入 Steering 队列
     - 不同 Session 的消息 → 重新排队
  3. processMessage(msg) → 路由到目标 Agent → runTurn()
  4. 停止 Steering 拦截器
  5. 消费剩余 Steering 队列 → 对每条调用 continue()
  6. 发送最终响应
```

**设计要点**:
- 同一个 Session 同时只有一个 Turn 在执行
- Turn 执行期间的新消息不排队等待新 Turn，而是作为 Steering 注入当前 Turn
- 这让用户可以在 Agent 执行长工具链时"补充指令"

### 2.3 第二层：Turn 迭代循环（核心）

**伪代码**:

```
function runTurn(context, turnState):
    // ── 准备阶段 ──
    history = session.getHistory(sessionKey)
    summary = session.getSummary(sessionKey)
    messages = buildMessages(systemPrompt, history, summary, userMessage)

    // ── 预算检查 ──
    if isOverContextBudget(messages, toolDefs, contextWindow):
        forceCompression(session, sessionKey)
        messages = rebuildMessages()  // 用压缩后的历史重建

    // ── 保存用户消息 ──
    session.addMessage(sessionKey, "user", userMessage)
    captureRestorePoint(history, summary)  // 用于 abort 回滚

    // ── 迭代循环 ──
    for iteration = 1 to maxIterations:
        // 中断检查
        if hardAbortRequested: rollbackAndReturn()
        if gracefulInterruptRequested:
            messages.append(interruptHintMessage)
            disableTools()

        // 注入 Steering 消息 + SubTurn 结果
        steeringMsgs = dequeueSteeringMessages()
        subturnResults = pollSubTurnResults()
        messages.appendAll(steeringMsgs + subturnResults)

        // 调用 LLM
        response = callLLMWithRetry(messages, toolDefs, model)

        // 无工具调用 → 结束
        if response.toolCalls is empty:
            finalContent = response.content
            break

        // 有工具调用 → 逐个执行
        messages.append(assistantMessage(response))
        session.addFullMessage(assistantMessage)

        for toolCall in response.toolCalls:
            result = hooks.beforeTool(toolCall)  // 钩子可修改/拒绝
            if not denied:
                result = executeTool(toolCall.name, toolCall.arguments)
                hooks.afterTool(toolCall, result)
            messages.append(toolResultMessage(toolCall.id, result))
            session.addFullMessage(toolResultMessage)

    // ── 收尾阶段 ──
    session.addMessage("assistant", finalContent)
    session.save()
    asyncTrigger: maybeSummarize(session, sessionKey)

    return finalContent
```

### 2.4 LLM 调用重试与错误恢复

```
function callLLMWithRetry(messages, tools, model):
    for retry = 0 to maxRetries:
        try:
            return provider.chat(messages, tools, model)
        catch TimeoutError:
            backoff(retry * 5 seconds)
            continue
        catch ContextLimitError:
            forceCompression(session, sessionKey)
            messages = rebuildMessages()
            continue
        catch other:
            throw
```

**关键设计**: 上下文超限不是致命错误，而是触发压缩 → 重建消息 → 重试。

### 2.5 中断机制

两种中断模式，支持从外部安全终止正在运行的 Turn：

| 模式 | 触发方式 | 行为 |
|------|----------|------|
| **Graceful** | 用户发送中断命令 | 在下一次 LLM 调用中注入 "请停止并总结" 的提示，禁用工具，让 LLM 自然收尾 |
| **Hard Abort** | 紧急停止 | 取消所有进行中的 LLM 调用和工具执行，回滚 Session 到 Turn 开始前的状态 |

```
function abortTurn(turnState):
    turnState.restoreSession()  // 回滚到 captureRestorePoint 的快照
    return "Turn aborted"
```

### 2.6 SubTurn（递归子 Agent）

子 Turn 允许工具在执行时递归调用 Agent 能力：

```
function spawnSubTurn(parentTurnState, config):
    // 限制检查
    if parentTurnState.depth >= maxDepth: error("depth limit")
    acquireConcurrencySemaphore(parent, timeout)

    // 创建隔离环境
    childContext = newIndependentContext(timeout)  // 不继承父 context
    ephemeralSession = newInMemorySession(maxSize=50)
    childAgent = shallowCopy(parentAgent, session=ephemeralSession)

    // 执行
    childTurnState = newTurnState(childAgent, config)
    childTurnState.depth = parent.depth + 1
    result = runTurn(childContext, childTurnState)

    // 结果传递
    if config.async:
        parent.pendingResults.send(result)  // 父 Turn 在下次迭代时消费
    return result
```

**设计约束**:

| 参数 | 建议默认值 | 说明 |
|------|------------|------|
| `maxDepth` | 3 | 防止无限递归 |
| `maxConcurrent` | 5 | 信号量控制，防止资源耗尽 |
| `timeout` | 5 分钟 | 每个子 Turn 独立超时 |
| `ephemeralMaxMessages` | 50 | 子 Turn 临时会话上限 |

---

## 三、消息机制设计

### 3.1 消息总线

消息总线是 Agent Loop 与外部世界（Discord、Telegram、CLI 等）之间的唯一通信通道。

```
                  ┌──────────────────────┐
   Discord ──→   │                      │ ──→ Discord
   Telegram ──→  │    MessageBus        │ ──→ Telegram
   CLI ──→       │                      │ ──→ CLI
   Webhook ──→   │  InboundChan         │ ──→ Webhook
   Cron ──→      │  PublishOutbound()   │
                  └──────────────────────┘
                         ↕
                    Agent Loop
```

**InboundMessage 结构**:

```
InboundMessage:
    Channel: string       // 来源渠道（"discord", "telegram", "cli"）
    ChatID: string        // 对话标识
    SenderID: string      // 发送者 ID
    Content: string       // 消息文本
    Media: string[]       // 媒体引用列表
    SessionKey: string    // 会话标识（可选，用于路由）
```

**OutboundMessage 结构**:

```
OutboundMessage:
    Channel: string
    ChatID: string
    Content: string
```

### 3.2 Steering Queue（转向队列）

**问题**: 用户在 Agent 执行长工具链（如：搜索 → 分析 → 写报告）期间发送新消息，应该怎么处理？

**方案**: 不启动新 Turn，而是将新消息注入当前 Turn 的下一次 LLM 迭代。

```
Steering 队列设计:
    storage: Map<SessionKey, Queue<Message>>

    enqueue(scope, message):
        storage[scope].push(message)

    dequeue(scope) -> Message[]:
        return storage[scope].drainAll()

    pendingCount(scope) -> int:
        return storage[scope].size()
```

**注入时机**: 每次 LLM 迭代开始前，从 Steering 队列取出所有消息，追加到 messages 中：

```
// 在 Turn Loop 的每次迭代开始时
steeringMsgs = steering.dequeue(sessionKey)
for msg in steeringMsgs:
    messages.append(msg)
    session.addFullMessage(sessionKey, msg)  // 持久化
```

### 3.3 系统提示词组装

系统提示词分为 **静态部分**（可缓存）和 **动态部分**（每次请求变化），最终合并为单条 system message：

```
function buildMessages(history, summary, userMessage, channel, sender):
    // 静态部分 — 基于文件变更自动失效缓存
    staticPrompt = cache.getOrBuild(
        key = hash(workspaceFiles.mtimes),
        builder = () => join(
            identity,          // Agent 身份描述 + 规则
            bootstrapFiles,    // 行为定义文件（如 AGENT.md）
            skillsSummary,     // 已安装技能的摘要
            memoryContext,     // 长期记忆 + 最近日志
        )
    )

    // 动态部分 — 每次请求重建
    dynamicContext = join(
        "当前时间: " + now(),
        "运行环境: " + os + arch,
        "会话: " + channel + "/" + chatID,
        "发送者: " + sender,
    )

    // 组合 system message
    systemContent = staticPrompt + dynamicContext
    if summary != "":
        systemContent += "CONTEXT_SUMMARY: " + summary

    return [
        { role: "system", content: systemContent },
        ...history,
        { role: "user", content: userMessage },
    ]
```

**缓存策略**: 静态提示词通过检查 workspace 文件的修改时间（mtime）来判断是否失效。无需主动清除，文件变更自动触发重建。

### 3.4 Hook 系统

可扩展的钩子系统允许在关键节点拦截和修改行为：

```
Hook 接口:
    BeforeLLM(request)  → (modifiedRequest, Decision)
    AfterLLM(response)  → (modifiedResponse, Decision)
    BeforeTool(toolCall) → (modifiedToolCall, Decision)
    AfterTool(toolCall, result) → (modifiedResult, Decision)

Decision 枚举:
    Continue     // 继续执行（可能已修改数据）
    Modify       // 同 Continue
    DenyTool     // 拒绝该工具调用（仅 BeforeTool）
    AbortTurn    // 中止当前 Turn
    HardAbort    // 强制中止 + 回滚
```

---

## 四、记忆系统设计

### 4.1 分层架构

```
┌──────────────────────────────────────────────────────┐
│ 层级 1: 对话历史（Session History）                     │
│ 范围: 单个会话                                         │
│ 生命周期: 会话存续期间                                  │
│ 存储: 结构化消息序列（user/assistant/tool + metadata）   │
│ 操作: 追加、截断、替换、摘要                             │
│ 持久化: Append-only JSONL + 元数据文件                  │
├──────────────────────────────────────────────────────┤
│ 层级 2: 会话摘要（Session Summary）                     │
│ 范围: 单个会话                                         │
│ 生命周期: 随对话历史更新                                 │
│ 存储: 自然语言文本                                      │
│ 操作: LLM 生成 / 紧急压缩标注                           │
│ 注入: 作为系统提示词的一部分发送给 LLM                   │
├──────────────────────────────────────────────────────┤
│ 层级 3: 长期记忆（Long-term Memory）                    │
│ 范围: 跨会话                                           │
│ 生命周期: 永久（Agent 主动管理）                         │
│ 存储: Markdown 文件                                     │
│ 操作: Agent 通过工具读写                                │
│ 注入: 作为系统提示词的一部分                             │
├──────────────────────────────────────────────────────┤
│ 层级 4: SubTurn 临时记忆                                │
│ 范围: 单个子 Turn                                      │
│ 生命周期: Turn 执行期间                                 │
│ 存储: 内存，固定上限                                    │
│ 操作: 追加、自动截断                                    │
│ 持久化: 无 | GC 回收                                   │
└──────────────────────────────────────────────────────┘
```

### 4.2 对话历史存储（Append-Only JSONL）

**文件结构**:
```
sessions/
├── chat_12345.jsonl       ← 每行一条 JSON Message
└── chat_12345.meta.json   ← 元数据
```

**Message 格式（每行）**:
```json
{"role":"user","content":"hello"}
{"role":"assistant","content":"","tool_calls":[{"id":"tc_1","type":"function","function":{"name":"web_search","arguments":"{\"query\":\"weather\"}"}}]}
{"role":"tool","content":"Today is sunny...","tool_call_id":"tc_1"}
{"role":"assistant","content":"Today's weather is sunny!"}
```

**Meta 格式**:
```json
{
    "key": "chat:12345",
    "summary": "用户询问了天气...",
    "skip": 10,
    "count": 25,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-03-24T22:00:00Z"
}
```

**核心操作语义**:

| 操作 | 实现 | 文件变更 |
|------|------|----------|
| [AddMessage](file:///Volumes/WorkSpace/Projects/Github/picoclaw/pkg/session/jsonl_backend.go#23-28) | JSON 序列化 → append 到 JSONL 末尾 → fsync → 更新 meta.count | JSONL: 追加一行 |
| [GetHistory](file:///Volumes/WorkSpace/Projects/Github/picoclaw/pkg/memory/store.go#18-21) | 读取 meta.skip → 扫描 JSONL 跳过前 skip 行 → 反序列化剩余行 | 只读 |
| [TruncateHistory(keepLast)](file:///Volumes/WorkSpace/Projects/Github/picoclaw/pkg/memory/store.go#29-32) | 计算 `skip = count - keepLast` → 写入 meta | 仅改 meta |
| [SetHistory(msgs)](file:///Volumes/WorkSpace/Projects/Github/picoclaw/pkg/agent/subturn.go#602-603) | 原子重写 JSONL → 重置 meta | 全量重写 |
| [Compact](file:///Volumes/WorkSpace/Projects/Github/picoclaw/pkg/memory/store.go#36-39) | 读 skip 后的活跃消息 → 原子重写 JSONL → 重置 skip=0 | 全量重写 |

**为什么用 Append-Only + 逻辑截断**:
1. **崩溃安全**: append + fsync 原子性好，断电不损坏已有数据
2. **写性能**: O(1) 追加，无需每次重写整个文件
3. **按需回收**: Compact 仅在 Save 时执行，避免频繁 I/O
4. **崩溃恢复**: meta 若过时（crash 在 append 和 meta update 之间），下次 [TruncateHistory](file:///Volumes/WorkSpace/Projects/Github/picoclaw/pkg/memory/store.go#29-32) 会重新计数修正

**并发控制**: 使用固定数量（如 64）的 sharded mutex，通过 session key 的哈希映射到锁，O(1) 内存。

### 4.3 会话摘要机制

#### 触发条件（满足任一）

```
function maybeSummarize(session, sessionKey):
    history = session.getHistory(sessionKey)
    tokenEstimate = estimateTokens(history)

    shouldSummarize =
        len(history) > SUMMARIZE_MESSAGE_THRESHOLD    // 默认 20
        OR tokenEstimate > contextWindow * SUMMARIZE_TOKEN_PERCENT / 100  // 默认 75%

    if shouldSummarize AND not alreadySummarizing(sessionKey):
        asyncRun: summarizeSession(session, sessionKey)
```

#### 摘要流程

```
function summarizeSession(session, sessionKey):
    history = session.getHistory(sessionKey)
    if len(history) <= 4: return  // 太短，不摘要

    // 1. 在 Turn 边界切割，保留最近的完整 Turn
    safeCut = findSafeTurnBoundary(history, len(history) - 4)
    if safeCut <= 0: return  // 无法安全切割
    toSummarize = history[:safeCut]
    keepCount = len(history) - safeCut

    // 2. 过滤超大消息（防止摘要本身超出 context window）
    validMessages = filter(toSummarize, msg =>
        msg.role in ["user", "assistant"]
        AND estimateTokens(msg) <= contextWindow / 2
    )

    // 3. 生成摘要
    if len(validMessages) > MAX_BATCH_SIZE:  // 默认 10
        // 分批摘要 + LLM 合并
        mid = findNearestUserMessage(validMessages, len/2)
        s1 = summarizeBatch(validMessages[:mid])
        s2 = summarizeBatch(validMessages[mid:])
        summary = llm("Merge these summaries: " + s1 + s2)
    else:
        summary = summarizeBatch(validMessages, existingSummary)

    // 4. 持久化
    session.setSummary(sessionKey, summary)
    session.truncateHistory(sessionKey, keepCount)
    session.save(sessionKey)  // 触发 Compact
```

#### Turn 边界安全切割

**核心规则**: 绝不在 `assistant(tool_calls)` 和对应的 `tool(result)` 之间切割。

```
function findSafeTurnBoundary(history, targetIndex):
    // Turn 边界 = 每个 role=="user" 消息的位置
    turnStarts = [i for i, msg in history if msg.role == "user"]

    // 优先找 targetIndex 之前最近的 Turn 边界
    for t in reversed(turnStarts):
        if t <= targetIndex and t > 0:
            return t

    // 没有安全边界 → 返回 0（表示无法切割）
    return 0
```

### 4.4 紧急压缩

当 context window 超限时的快速降级方案：

```
function forceCompression(session, sessionKey):
    history = session.getHistory(sessionKey)
    if len(history) <= 2: return

    // 在 Turn 边界处丢弃前一半
    turns = parseTurnBoundaries(history)
    if len(turns) >= 2:
        mid = turns[len(turns) / 2]
    else:
        mid = findSafeTurnBoundary(history, len(history) / 2)

    if mid <= 0:
        // 最后手段：只保留最后一条 user 消息
        kept = [lastUserMessage(history)]
    else:
        kept = history[mid:]

    dropped = len(history) - len(kept)

    // 在 Summary 中标注压缩事件
    note = "[Emergency compression dropped " + dropped + " messages]"
    session.setSummary(sessionKey, existingSummary + note)
    session.setHistory(sessionKey, kept)
    session.save(sessionKey)
```

### 4.5 长期记忆

Agent 通过文件系统工具主动维护的跨会话知识存储：

```
workspace/memory/
├── MEMORY.md                ← 核心长期记忆
└── YYYYMM/
    └── YYYYMMDD.md          ← 每日笔记
```

**注入方式**: 系统提示词构建时读取这些文件，拼入 system message：

```
function getMemoryContext():
    longTerm = readFile("memory/MEMORY.md")
    recentNotes = readRecentDailyNotes(3)  // 最近 3 天
    return format(longTerm, recentNotes)
```

**管理方式**: 系统提示词中指示 Agent：
> "When interacting, if something seems memorable, update `memory/MEMORY.md`"

Agent 使用 `read_file` / `write_file` 工具自行决定何时更新。

### 4.6 上下文预算估算

用于在调 LLM 前预判 context window 是否会超限：

```
function isOverContextBudget(contextWindow, messages, toolDefs, maxTokens):
    msgTokens = sum(estimateMessageTokens(msg) for msg in messages)
    toolTokens = estimateToolDefsTokens(toolDefs)
    total = msgTokens + toolTokens + maxTokens  // maxTokens = 输出预留

    return total > contextWindow

function estimateMessageTokens(msg):
    chars = runeCount(msg.content)
    chars += runeCount(msg.reasoningContent)
    chars += sum(len(tc.id) + len(tc.function.name) + len(tc.function.arguments)
                 for tc in msg.toolCalls)
    chars += OVERHEAD_PER_MESSAGE  // ~12
    tokens = chars * 2 / 5  // 2.5 chars/token heuristic
    tokens += len(msg.media) * MEDIA_TOKENS_PER_ITEM  // ~256
    return tokens
```

---

## 五、数据流总览

```
用户消息
  │
  ▼
① 消息总线接收 (InboundMessage)
  │
  ▼
② 路由到目标 Agent + 解析 SessionKey
  │
  ▼
③ 加载记忆上下文
  ├── Session History (JSONL)
  ├── Session Summary (meta.json)
  └── Long-term Memory (MEMORY.md + 每日笔记)
  │
  ▼
④ 组装 messages[]
  ├── system: [静态提示词(缓存)] + [动态上下文] + [Summary]
  ├── history: [...已有对话...]
  └── user: [当前消息]
  │
  ▼
⑤ 预算检查
  └── 超限 → forceCompression → 重新组装
  │
  ▼
⑥ 保存用户消息 + 快照 RestorePoint
  │
  ▼
⑦ Turn Loop (最多 maxIterations 次):
  ├── 注入 Steering + SubTurn Results
  ├── hooks.beforeLLM()
  ├── callLLM() → retry on timeout/context-limit
  ├── hooks.afterLLM()
  ├── 无工具 → break
  └── 有工具 → 执行 → 保存结果 → 继续
  │
  ▼
⑧ 保存最终响应 + Save(Compact)
  │
  ▼
⑨ 发送响应 (OutboundMessage)
  │
  ▼
⑩ 异步: maybeSummarize()
  └── 超阈值 → LLM 生成摘要 → 截断历史 → Save
```

---

## 六、实现建议

### 最小可行实现（MVP）

按优先级排序：

1. **Turn Loop + LLM 调用**: 迭代式 tool-use 循环是核心
2. **Session 持久化**: 先用简单 JSON 文件，后续迁移 JSONL
3. **上下文预算 + 紧急压缩**: 防止 context window 溢出
4. **异步摘要**: 防止历史无限增长
5. **消息总线 + 多渠道**: 解耦 Agent 与具体平台
6. **Steering 队列**: 提升交互体验
7. **SubTurn**: 仅在需要递归 Agent 能力时实现
8. **Hook 系统**: 用于审计、过滤、监控

### 关键设计决策

| 决策点 | 推荐方案 | 原因 |
|--------|----------|------|
| 存储格式 | Append-only JSONL | 崩溃安全、写性能好 |
| 截断方式 | 逻辑 skip + 定期 Compact | 避免频繁重写 |
| 压缩触发 | 双触发（消息数 OR token%） | 覆盖长对话和大工具输出两种场景 |
| 切割边界 | Turn 边界对齐 | 防止拆散 tool call 序列 |
| SubTurn 上下文 | 独立 context，不继承父 | 子 Turn 超时不拖垮父 Turn |
| Session 并发 | Sharded mutex | O(1) 内存，优于 per-session lock |
| 系统提示词 | 静态缓存 + 动态拼接 | 减少重复文件 I/O，兼容 LLM 前缀缓存 |
