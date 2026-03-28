# 服务智能启动 + ServiceManager Bug 修复 — 设计文档

> **Status: draft**

## 目标

1. **智能项目检测**：扫描项目目录，自动识别项目类型（Node.js / Python / Go / Rust / Makefile），解析配置文件提取可用命令列表，优先从 README.md 提取启动方式。
2. **Bug 修复**：修复 `ServiceManager` 现有缺陷——进程组管理、进程状态误判、日志全量读取、日志文件模式。

## 非目标

- 不做服务状态持久化（本次不涉及重启后恢复）
- 不做服务健康检查 / 自动重启
- 不自动执行启动命令——只提供候选列表，由 Agent 决策

---

## 一、项目检测器：`service/detector.py`

### 数据结构

```python
@dataclass
class CommandEntry:
    name: str        # 如 "dev", "build", "test"
    command: str     # 实际命令 "npm run dev"
    source: str      # 来源: "readme" | "package.json" | "Makefile" | ...

@dataclass
class ProjectProfile:
    path: str
    project_type: str                # "node" | "python" | "go" | "rust" | "makefile" | "unknown"
    readme_summary: str              # README.md 前 N 行，无则空
    available_commands: list[CommandEntry]
```

### 检测优先级

1. **README.md（最高优先级）**  
   读取项目根目录的 `README.md`（取前 200 行）。用正则匹配 fenced code block 中的启动命令模式（`npm`, `yarn`, `pnpm`, `python`, `uvicorn`, `gunicorn`, `go run`, `cargo run`, `make` 等）。匹配到的命令 `source="readme"`。同时提取前几行作为项目描述 `readme_summary`。

2. **配置文件解析（补充）**  
   无论 README 是否有结果，都继续扫描以下文件，去重后合并到 `available_commands`：

   | 标志文件 | project_type | 解析方式 |
   |----------|-------------|---------|
   | `package.json` | `"node"` | 读取 `scripts` 字段 → 每个 key 生成 `npm run <key>` |
   | `pyproject.toml` | `"python"` | 读取 `[project.scripts]` 和 `[tool.poetry.scripts]` |
   | `requirements.txt` / `setup.py` | `"python"` | 仅标记类型，无具体 scripts |
   | `Makefile` | `"makefile"` | 正则提取 target 名（非 `.PHONY`、非 `_` 前缀）→ `make <target>` |
   | `go.mod` | `"go"` | 检查是否有 `cmd/` 目录或 `main.go` → `go run .` / `go run ./cmd/...` |
   | `Cargo.toml` | `"rust"` | 读取 `[[bin]]` section → `cargo run --bin <name>`；无则 `cargo run` |

3. **多类型共存**：project_type 取第一个匹配的（按上表顺序），但 `available_commands` 包含所有来源的命令。

### 接口

```python
class ProjectDetector:
    def detect(self, project_path: str) -> ProjectProfile:
        """同步方法，扫描目录返回项目 profile。"""
```

独立的纯函数式模块，不依赖 `ServiceManager` 状态。`ServiceManager` 持有一个 `ProjectDetector` 实例并暴露 `detect_project()` 方法。

---

## 二、ServiceManager Bug 修复

### 2.1 进程组管理

**问题**：`create_subprocess_shell` 的 PID 是 shell 进程，`os.kill(pid, SIGTERM)` 只杀 shell，子进程变孤儿。

**修复**：
- `start()` 加 `start_new_session=True`，让子进程成为新 session leader
- `stop()` 改用 `os.killpg(os.getpgid(pid), signal.SIGTERM)` 杀整个进程组
- SIGKILL 同理改用 `os.killpg`

### 2.2 `_is_process_running` 误判

**问题**：`PermissionError` 表示进程存在但无权限，当前返回 `False`。

**修复**：`PermissionError` 改为返回 `True`。

```python
@staticmethod
def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
```

### 2.3 日志尾部读取

**问题**：`logs()` 用 `read_text()` 全量读文件再切片，大日志时内存爆炸。

**修复**：从文件尾部反向读取，只读需要的字节量。

```python
async def logs(self, project: str, name: str, lines: int = 50) -> str:
    # 从文件末尾读取最多 64KB，按行切割取最后 N 行
```

### 2.4 日志文件 binary 模式

**问题**：`open(log_file, "a", encoding="utf-8")` 创建 TextIOWrapper，对 subprocess 无意义。

**修复**：改为 `open(log_file, "ab")`，binary append 模式。

### 2.5 cwd 确保是项目目录

现有 tool 层已传 `cwd=proj.path`，这点不变。在 `ServiceManager.start()` 中增加校验 cwd 目录是否存在。

---

## 三、工具层变化

### 新增 tool: `inspect_project`

```python
@agent.tool
def inspect_project(ctx: RunContext[Any], project: str = "") -> str:
    """检测项目类型和可用启动命令"""
```

调用 `sm.detect_project(proj.path)`，格式化返回：
```
📂 项目: myapp (Node.js)
📄 README 摘要: A web dashboard for ...

可用命令:
  [readme]        npm run dev
  [package.json]  npm run dev
  [package.json]  npm run build
  [package.json]  npm run test
  [package.json]  npm run lint
```

### `start_service` 不变

仍接收显式 command 参数。Agent 先调 `inspect_project` 获取候选，再调 `start_service` 执行。两步分离，保持灵活性。

---

## 四、文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `src/chatcc/service/detector.py` | 项目检测器，解析配置文件提取命令 |
| Modify | `src/chatcc/service/manager.py` | 集成 detector；修复进程组、进程判断、日志读取、文件模式 |
| Modify | `src/chatcc/tools/service_tools.py` | 新增 `inspect_project` tool |
| Create | `tests/test_detector.py` | 检测器单元测试（各项目类型 fixture） |
| Modify | `tests/test_service_manager.py` | 补充进程组、日志尾读等测试 |
| Modify | `tests/test_tools_service.py` | 新增 `inspect_project` tool 测试 |

---

## 五、典型交互流

```
用户: "启动 myapp 的开发服务器"

Agent 内部:
  1. inspect_project("myapp")
     → 扫描 /workspace/projects/myapp/
     → 读 README.md → 找到 "npm run dev"
     → 解析 package.json → scripts: dev, build, test, lint
     → 返回 ProjectProfile

  2. Agent 看到 README 推荐 "npm run dev"，决定使用

  3. start_service("dev-server", "npm run dev", "myapp")
     → ServiceManager.start("myapp", "dev-server", "npm run dev", cwd="/workspace/projects/myapp")
     → start_new_session=True
     → 返回 RunningService(pid=...)

Agent 回复: "已启动 myapp 的开发服务器 (npm run dev, PID: 12345)"
```
