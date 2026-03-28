# 服务智能启动 — 实现计划

> **Status: ✅ COMPLETED** (2026-03-28)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 自动检测项目类型并提取可用启动命令，同时修复 ServiceManager 的进程管理、日志读取等 bug。

**Architecture:** 新增 `service/detector.py` 模块负责扫描项目目录和解析配置文件，`ServiceManager` 集成 detector 并暴露 `detect_project()` 方法。README.md 作为最高优先级的命令来源，配置文件（package.json / pyproject.toml / Makefile / go.mod / Cargo.toml）作为补充。工具层新增 `inspect_project` tool 供 Agent 调用。

**Tech Stack:** Python 3.12, asyncio, tomllib (stdlib), json, re, pytest

---

## File Structure

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `src/chatcc/service/detector.py` | `ProjectDetector` — 扫描目录、检测项目类型、解析配置文件、提取命令 |
| Modify | `src/chatcc/service/manager.py` | 集成 detector；修复进程组管理、`_is_process_running`、日志尾读、binary 模式 |
| Modify | `src/chatcc/tools/service_tools.py` | 新增 `inspect_project` tool |
| Create | `tests/test_detector.py` | detector 单元测试 |
| Modify | `tests/test_service_manager.py` | bug 修复相关测试 |
| Modify | `tests/test_tools_service.py` | `inspect_project` tool 测试 |

---

## Chunk 1: ServiceManager Bug 修复

### Task 1: 修复 `_is_process_running` 的 PermissionError 处理

**Files:**
- Modify: `src/chatcc/service/manager.py:161-167`
- Test: `tests/test_service_manager.py`

- [x] **Step 1: 写失败测试**

在 `tests/test_service_manager.py` 底部追加：

```python
def test_is_process_running_permission_error():
    """PermissionError means process exists but no permission — should return True."""
    with patch("os.kill", side_effect=PermissionError("not permitted")):
        assert ServiceManager._is_process_running(99999) is True


def test_is_process_running_not_found():
    with patch("os.kill", side_effect=ProcessLookupError()):
        assert ServiceManager._is_process_running(99999) is False


def test_is_process_running_ok():
    with patch("os.kill"):
        assert ServiceManager._is_process_running(99999) is True
```

需要在文件顶部加 `from unittest.mock import patch`。

- [x] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_service_manager.py::test_is_process_running_permission_error -v`
Expected: FAIL — `assert False is True`

- [x] **Step 3: 修复实现**

在 `src/chatcc/service/manager.py` 中替换 `_is_process_running`：

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

- [x] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_service_manager.py -k "is_process_running" -v`
Expected: 3 PASSED

- [x] **Step 5: 提交**

```bash
git add src/chatcc/service/manager.py tests/test_service_manager.py
git commit -m "fix(service): _is_process_running returns True on PermissionError"
```

---

### Task 2: 进程组管理 — start_new_session + killpg

**Files:**
- Modify: `src/chatcc/service/manager.py:57-62` (start), `80-108` (stop)
- Test: `tests/test_service_manager.py`

- [x] **Step 1: 写失败测试**

在 `tests/test_service_manager.py` 追加：

```python
@pytest.mark.asyncio
async def test_stop_kills_process_group(svc_manager: ServiceManager, tmp_path: Path):
    """stop() should kill the process group, not just the shell PID."""
    svc = await svc_manager.start(
        "proj", "nested", "sleep 60 & sleep 60 & wait", cwd=str(tmp_path)
    )
    pid = svc.pid
    # The process should be a session leader (new session)
    pgid = os.getpgid(pid)
    assert pgid == pid  # start_new_session=True makes pid == pgid

    result = await svc_manager.stop("proj", "nested")
    assert result is True
    await asyncio.sleep(0.2)
    assert not ServiceManager._is_process_running(pid)
```

需要在文件顶部加 `import os`。

- [x] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_service_manager.py::test_stop_kills_process_group -v`
Expected: FAIL — `assert pgid == pid` fails（因为没有 `start_new_session=True`）

- [x] **Step 3: 修改 start() 加 start_new_session=True**

在 `src/chatcc/service/manager.py` 的 `start()` 方法中，`create_subprocess_shell` 调用改为：

```python
proc = await asyncio.create_subprocess_shell(
    command,
    cwd=cwd,
    stdout=log_fh,
    stderr=log_fh,
    start_new_session=True,
)
```

- [x] **Step 4: 修改 stop() 使用 os.killpg**

在 `src/chatcc/service/manager.py` 的 `stop()` 方法中，替换信号发送逻辑：

```python
async def stop(self, project: str, name: str) -> bool:
    """Stop a service. SIGTERM first, then SIGKILL after 3s.
    Returns True if service was stopped."""
    service = self._get_service(project, name)
    if not service:
        return False

    if not self._is_process_running(service.pid):
        self._remove_service(project, name)
        return True

    try:
        os.killpg(os.getpgid(service.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        self._remove_service(project, name)
        return True

    for _ in range(30):
        await asyncio.sleep(0.1)
        if not self._is_process_running(service.pid):
            self._remove_service(project, name)
            return True

    try:
        os.killpg(os.getpgid(service.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    self._remove_service(project, name)
    return True
```

- [x] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_service_manager.py -v`
Expected: ALL PASSED

- [x] **Step 6: 提交**

```bash
git add src/chatcc/service/manager.py tests/test_service_manager.py
git commit -m "fix(service): use process groups for reliable subprocess cleanup"
```

---

### Task 3: 日志 binary 模式 + 尾部读取

**Files:**
- Modify: `src/chatcc/service/manager.py:55` (open 模式), `128-139` (logs 方法)
- Test: `tests/test_service_manager.py`

- [x] **Step 1: 写日志尾读测试**

在 `tests/test_service_manager.py` 追加：

```python
@pytest.mark.asyncio
async def test_logs_tail_read(svc_manager: ServiceManager, tmp_path: Path):
    """logs() should only return the last N lines without loading the entire file."""
    svc = await svc_manager.start(
        "proj", "multiline",
        "for i in $(seq 1 100); do echo line_$i; done && sleep 1",
        cwd=str(tmp_path),
    )
    await asyncio.sleep(1.0)
    output = await svc_manager.logs("proj", "multiline", lines=5)
    lines = output.strip().splitlines()
    assert len(lines) == 5
    assert lines[-1] == "line_100"
```

- [x] **Step 2: 运行测试验证通过（当前实现也能通过，但我们要改内部实现）**

Run: `pytest tests/test_service_manager.py::test_logs_tail_read -v`
Expected: PASS（功能不变，只是内部优化）

- [x] **Step 3: 改 open 为 binary 模式**

在 `src/chatcc/service/manager.py` 的 `start()` 中替换：

```python
log_fh = open(log_file, "ab")
```

- [x] **Step 4: 改 logs() 为尾部读取**

替换 `logs()` 方法：

```python
async def logs(self, project: str, name: str, lines: int = 50) -> str:
    """Read last N lines from service log file."""
    service = self._get_service(project, name)
    if not service:
        return f"服务 '{name}' 未找到"

    if not service.log_file.exists():
        return "(无日志)"

    chunk_size = 8192
    result_lines: list[str] = []
    with open(service.log_file, "rb") as f:
        f.seek(0, 2)
        remaining = f.tell()
        while remaining > 0 and len(result_lines) < lines + 1:
            read_size = min(chunk_size, remaining)
            remaining -= read_size
            f.seek(remaining)
            chunk = f.read(read_size).decode("utf-8", errors="replace")
            result_lines = chunk.splitlines() + result_lines
    return "\n".join(result_lines[-lines:])
```

- [x] **Step 5: 运行全部测试**

Run: `pytest tests/test_service_manager.py -v`
Expected: ALL PASSED

- [x] **Step 6: 提交**

```bash
git add src/chatcc/service/manager.py tests/test_service_manager.py
git commit -m "fix(service): binary log mode and tail-read for logs()"
```

---

## Chunk 2: 项目检测器 `detector.py`

### Task 4: 数据结构 + Node.js 检测

**Files:**
- Create: `src/chatcc/service/detector.py`
- Create: `tests/test_detector.py`

- [x] **Step 1: 写 Node.js 检测的失败测试**

创建 `tests/test_detector.py`：

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatcc.service.detector import CommandEntry, ProjectDetector, ProjectProfile


@pytest.fixture
def detector() -> ProjectDetector:
    return ProjectDetector()


def test_detect_node_project(detector: ProjectDetector, tmp_path: Path):
    pkg = {
        "name": "test-app",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "test": "vitest",
            "lint": "eslint .",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))

    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "node"
    names = [c.name for c in profile.available_commands]
    assert "dev" in names
    assert "build" in names
    cmd = next(c for c in profile.available_commands if c.name == "dev")
    assert cmd.command == "npm run dev"
    assert cmd.source == "package.json"


def test_detect_unknown_project(detector: ProjectDetector, tmp_path: Path):
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "unknown"
    assert profile.available_commands == []
```

- [x] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'chatcc.service.detector'`

- [x] **Step 3: 实现数据结构 + Node.js 检测**

创建 `src/chatcc/service/detector.py`：

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CommandEntry:
    name: str
    command: str
    source: str


@dataclass
class ProjectProfile:
    path: str
    project_type: str = "unknown"
    readme_summary: str = ""
    available_commands: list[CommandEntry] = field(default_factory=list)


class ProjectDetector:
    _MAX_README_LINES = 200

    _TYPE_PRIORITY = [
        ("package.json", "node"),
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("setup.py", "python"),
        ("go.mod", "go"),
        ("Cargo.toml", "rust"),
        ("Makefile", "makefile"),
    ]

    def detect(self, project_path: str) -> ProjectProfile:
        root = Path(project_path)
        profile = ProjectProfile(path=project_path)

        profile.readme_summary, readme_cmds = self._parse_readme(root)
        profile.available_commands.extend(readme_cmds)

        for marker, ptype in self._TYPE_PRIORITY:
            if (root / marker).exists() and profile.project_type == "unknown":
                profile.project_type = ptype

        config_cmds = self._parse_config_files(root)
        seen = {(c.name, c.command) for c in profile.available_commands}
        for cmd in config_cmds:
            if (cmd.name, cmd.command) not in seen:
                profile.available_commands.append(cmd)
                seen.add((cmd.name, cmd.command))

        return profile

    # ── README parsing ──────────────────────────────────────────────

    _CMD_PATTERN = re.compile(
        r"^\s*\$?\s*((?:npm|yarn|pnpm)\s+run\s+\S+|"
        r"(?:python|python3|uvicorn|gunicorn|flask|django-admin)\s+\S+.*|"
        r"go\s+run\s+\S+.*|"
        r"cargo\s+(?:run|build|test)\b.*|"
        r"make\s+\S+.*)",
        re.MULTILINE,
    )

    def _parse_readme(
        self, root: Path
    ) -> tuple[str, list[CommandEntry]]:
        readme = root / "README.md"
        if not readme.exists():
            return "", []

        try:
            text = readme.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "", []

        lines = text.splitlines()[: self._MAX_README_LINES]
        summary_lines = []
        for line in lines[:20]:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                summary_lines.append(stripped)
            if len(summary_lines) >= 3:
                break
        summary = " ".join(summary_lines)

        cmds: list[CommandEntry] = []
        seen: set[str] = set()
        for m in self._CMD_PATTERN.finditer("\n".join(lines)):
            raw = m.group(1).strip()
            if raw not in seen:
                name = raw.split()[-1] if len(raw.split()) <= 3 else raw.split()[1]
                cmds.append(CommandEntry(name=name, command=raw, source="readme"))
                seen.add(raw)

        return summary, cmds

    # ── Config file parsers ─────────────────────────────────────────

    def _parse_config_files(self, root: Path) -> list[CommandEntry]:
        cmds: list[CommandEntry] = []
        cmds.extend(self._parse_package_json(root))
        cmds.extend(self._parse_pyproject_toml(root))
        cmds.extend(self._parse_makefile(root))
        cmds.extend(self._parse_go_mod(root))
        cmds.extend(self._parse_cargo_toml(root))
        return cmds

    def _parse_package_json(self, root: Path) -> list[CommandEntry]:
        pkg_file = root / "package.json"
        if not pkg_file.exists():
            return []
        try:
            data = json.loads(pkg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        scripts = data.get("scripts", {})
        return [
            CommandEntry(name=k, command=f"npm run {k}", source="package.json")
            for k in scripts
        ]

    def _parse_pyproject_toml(self, root: Path) -> list[CommandEntry]:
        toml_file = root / "pyproject.toml"
        if not toml_file.exists():
            return []
        try:
            import tomllib
            data = tomllib.loads(toml_file.read_text(encoding="utf-8"))
        except (ImportError, OSError, Exception):
            return []
        cmds: list[CommandEntry] = []
        for section in ("project", "tool.poetry"):
            scripts = data
            for key in section.split("."):
                scripts = scripts.get(key, {})
            scripts = scripts.get("scripts", {})
            for name, entry in scripts.items():
                cmd_str = entry if isinstance(entry, str) else str(entry)
                cmds.append(
                    CommandEntry(name=name, command=cmd_str, source="pyproject.toml")
                )
        return cmds

    def _parse_makefile(self, root: Path) -> list[CommandEntry]:
        makefile = root / "Makefile"
        if not makefile.exists():
            return []
        try:
            text = makefile.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        targets: list[CommandEntry] = []
        for m in re.finditer(r"^([a-zA-Z][a-zA-Z0-9_-]*):", text, re.MULTILINE):
            name = m.group(1)
            targets.append(
                CommandEntry(name=name, command=f"make {name}", source="Makefile")
            )
        return targets

    def _parse_go_mod(self, root: Path) -> list[CommandEntry]:
        if not (root / "go.mod").exists():
            return []
        cmds: list[CommandEntry] = []
        if (root / "main.go").exists():
            cmds.append(CommandEntry(name="run", command="go run .", source="go.mod"))
        cmd_dir = root / "cmd"
        if cmd_dir.is_dir():
            for sub in sorted(cmd_dir.iterdir()):
                if sub.is_dir() and any(sub.glob("*.go")):
                    cmds.append(
                        CommandEntry(
                            name=sub.name,
                            command=f"go run ./cmd/{sub.name}",
                            source="go.mod",
                        )
                    )
        if not cmds:
            cmds.append(CommandEntry(name="run", command="go run .", source="go.mod"))
        return cmds

    def _parse_cargo_toml(self, root: Path) -> list[CommandEntry]:
        cargo_file = root / "Cargo.toml"
        if not cargo_file.exists():
            return []
        cmds = [
            CommandEntry(name="run", command="cargo run", source="Cargo.toml"),
            CommandEntry(name="build", command="cargo build", source="Cargo.toml"),
            CommandEntry(name="test", command="cargo test", source="Cargo.toml"),
        ]
        try:
            import tomllib
            data = tomllib.loads(cargo_file.read_text(encoding="utf-8"))
            bins = data.get("bin", [])
            for b in bins:
                if "name" in b:
                    cmds.append(
                        CommandEntry(
                            name=b["name"],
                            command=f"cargo run --bin {b['name']}",
                            source="Cargo.toml",
                        )
                    )
        except Exception:
            pass
        return cmds
```

- [x] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_detector.py -v`
Expected: 2 PASSED

- [x] **Step 5: 提交**

```bash
git add src/chatcc/service/detector.py tests/test_detector.py
git commit -m "feat(service): add ProjectDetector with Node.js support"
```

---

### Task 5: Python / Makefile / Go / Rust 检测测试

**Files:**
- Test: `tests/test_detector.py`

- [x] **Step 1: 追加各项目类型测试**

在 `tests/test_detector.py` 底部追加：

```python
def test_detect_python_pyproject(detector: ProjectDetector, tmp_path: Path):
    toml_content = """
[project]
name = "myapp"

[project.scripts]
serve = "uvicorn myapp:app"
migrate = "alembic upgrade head"
"""
    (tmp_path / "pyproject.toml").write_text(toml_content)
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "python"
    names = [c.name for c in profile.available_commands]
    assert "serve" in names
    assert "migrate" in names


def test_detect_python_requirements_only(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("flask==3.0\n")
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "python"
    assert profile.available_commands == []


def test_detect_makefile(detector: ProjectDetector, tmp_path: Path):
    makefile = "build:\n\tgo build .\n\ntest:\n\tgo test ./...\n\nrun:\n\t./app\n"
    (tmp_path / "Makefile").write_text(makefile)
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "makefile"
    names = [c.name for c in profile.available_commands]
    assert "build" in names
    assert "test" in names
    assert "run" in names


def test_detect_go_with_cmd_dir(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/app\n\ngo 1.22\n")
    cmd_dir = tmp_path / "cmd" / "server"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "main.go").write_text("package main\n")
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "go"
    cmds = {c.name: c.command for c in profile.available_commands}
    assert cmds["server"] == "go run ./cmd/server"


def test_detect_go_with_main(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/app\n\ngo 1.22\n")
    (tmp_path / "main.go").write_text("package main\n")
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "go"
    assert any(c.command == "go run ." for c in profile.available_commands)


def test_detect_rust(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"\nversion = "0.1.0"\n')
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "rust"
    names = [c.name for c in profile.available_commands]
    assert "run" in names
    assert "build" in names
    assert "test" in names
```

- [x] **Step 2: 运行测试验证通过**

Run: `pytest tests/test_detector.py -v`
Expected: ALL PASSED (8 tests)

- [x] **Step 3: 提交**

```bash
git add tests/test_detector.py
git commit -m "test(service): add detector tests for Python, Makefile, Go, Rust"
```

---

### Task 6: README 优先级检测

**Files:**
- Test: `tests/test_detector.py`

- [x] **Step 1: 写 README 优先级测试**

在 `tests/test_detector.py` 底部追加：

```python
def test_readme_commands_have_highest_priority(
    detector: ProjectDetector, tmp_path: Path
):
    readme = """# My App

A simple web app.

## Quick Start

```bash
npm run dev
```
"""
    pkg = {"name": "app", "scripts": {"dev": "vite", "build": "vite build"}}
    (tmp_path / "README.md").write_text(readme)
    (tmp_path / "package.json").write_text(json.dumps(pkg))

    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "node"
    assert profile.readme_summary != ""

    first_cmd = profile.available_commands[0]
    assert first_cmd.source == "readme"
    assert "npm run dev" in first_cmd.command

    sources = [c.source for c in profile.available_commands]
    assert "readme" in sources
    assert "package.json" in sources


def test_readme_no_commands(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "README.md").write_text("# Hello\n\nJust a readme with no commands.\n")
    profile = detector.detect(str(tmp_path))
    assert profile.readme_summary != ""
    assert profile.available_commands == []


def test_readme_dedup_with_config(detector: ProjectDetector, tmp_path: Path):
    """Same command from README and package.json should not appear twice."""
    readme = "## Start\n\n```\nnpm run dev\n```\n"
    pkg = {"name": "app", "scripts": {"dev": "vite"}}
    (tmp_path / "README.md").write_text(readme)
    (tmp_path / "package.json").write_text(json.dumps(pkg))

    profile = detector.detect(str(tmp_path))
    dev_cmds = [c for c in profile.available_commands if c.command == "npm run dev"]
    assert len(dev_cmds) == 1
    assert dev_cmds[0].source == "readme"
```

- [x] **Step 2: 运行测试验证通过**

Run: `pytest tests/test_detector.py -v`
Expected: ALL PASSED (11 tests)

- [x] **Step 3: 提交**

```bash
git add tests/test_detector.py
git commit -m "test(service): README priority and dedup tests for detector"
```

---

## Chunk 3: 集成层 — ServiceManager + Tool

### Task 7: ServiceManager 集成 detector

**Files:**
- Modify: `src/chatcc/service/manager.py`
- Test: `tests/test_service_manager.py`

- [x] **Step 1: 写集成测试**

在 `tests/test_service_manager.py` 底部追加：

```python
@pytest.mark.asyncio
async def test_detect_project(svc_manager: ServiceManager, tmp_path: Path):
    pkg = {"name": "web", "scripts": {"dev": "vite", "build": "vite build"}}
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    (proj_dir / "package.json").write_text(json.dumps(pkg))

    profile = svc_manager.detect_project(str(proj_dir))
    assert profile.project_type == "node"
    assert any(c.name == "dev" for c in profile.available_commands)
```

需要在文件顶部加 `import json`。

- [x] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_service_manager.py::test_detect_project -v`
Expected: FAIL — `AttributeError: 'ServiceManager' object has no attribute 'detect_project'`

- [x] **Step 3: 在 ServiceManager 集成 detector**

在 `src/chatcc/service/manager.py` 顶部加 import：

```python
from chatcc.service.detector import ProjectDetector, ProjectProfile
```

在 `ServiceManager.__init__` 中加：

```python
self._detector = ProjectDetector()
```

新增方法：

```python
def detect_project(self, project_path: str) -> ProjectProfile:
    """Detect project type and available commands."""
    return self._detector.detect(project_path)
```

- [x] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_service_manager.py -v`
Expected: ALL PASSED

- [x] **Step 5: 提交**

```bash
git add src/chatcc/service/manager.py tests/test_service_manager.py
git commit -m "feat(service): integrate ProjectDetector into ServiceManager"
```

---

### Task 8: 新增 `inspect_project` tool

**Files:**
- Modify: `src/chatcc/tools/service_tools.py`
- Test: `tests/test_tools_service.py`

- [x] **Step 1: 写 tool 测试**

在 `tests/test_tools_service.py` 底部追加：

```python
def test_inspect_project_success(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("web", str(tmp_path / "web"))
    (Path(pm.get_project("web").path) / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite","build":"tsc"}}'
    )
    sm = MagicMock()
    from chatcc.service.detector import CommandEntry, ProjectProfile
    sm.detect_project = MagicMock(
        return_value=ProjectProfile(
            path=pm.get_project("web").path,
            project_type="node",
            readme_summary="A web app",
            available_commands=[
                CommandEntry(name="dev", command="npm run dev", source="package.json"),
                CommandEntry(name="build", command="npm run build", source="package.json"),
            ],
        )
    )
    deps = AgentDeps(project_manager=pm, service_manager=sm)
    fn = dispatcher.agent._function_toolset.tools["inspect_project"].function
    out = fn(_ctx(deps), "")
    assert "node" in out.lower() or "Node" in out
    assert "npm run dev" in out


def test_inspect_project_no_manager(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["inspect_project"].function
    out = fn(_ctx(AgentDeps()))
    assert "未初始化" in out
```

需要在文件顶部加 `from pathlib import Path`。

- [x] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_tools_service.py::test_inspect_project_success -v`
Expected: FAIL — `KeyError: 'inspect_project'`

- [x] **Step 3: 在 service_tools.py 新增 inspect_project**

在 `src/chatcc/tools/service_tools.py` 的 `register_service_tools` 函数中，`service_logs` 之后追加：

```python
    @agent.tool
    def inspect_project(ctx: RunContext[Any], project: str = "") -> str:
        """检测项目类型和可用启动命令"""
        sm = ctx.deps.service_manager
        pm = ctx.deps.project_manager
        if not sm or not pm:
            return "错误: 管理器未初始化"

        if project:
            proj = pm.get_project(project)
        else:
            proj = pm.default_project
        if not proj:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        profile = sm.detect_project(proj.path)

        lines = [f"项目: {proj.name} ({profile.project_type})"]
        if profile.readme_summary:
            lines.append(f"简介: {profile.readme_summary}")
        if profile.available_commands:
            lines.append("")
            lines.append("可用命令:")
            for cmd in profile.available_commands:
                lines.append(f"  [{cmd.source}] {cmd.name}: {cmd.command}")
        else:
            lines.append("未检测到可用命令")
        return "\n".join(lines)
```

- [x] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_tools_service.py -v`
Expected: ALL PASSED

- [x] **Step 5: 运行全量测试**

Run: `pytest tests/ -v`
Expected: ALL PASSED

- [x] **Step 6: 提交**

```bash
git add src/chatcc/tools/service_tools.py tests/test_tools_service.py
git commit -m "feat(service): add inspect_project tool for smart startup discovery"
```
