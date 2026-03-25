from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic_ai import Agent, RunContext

from chatcc.config import load_config

DEFAULT_COMMAND_TIMEOUT = 30.0
MAX_OUTPUT_CHARS = 4000


def is_project_within_workspace(project_path: str, workspace_root: str) -> bool:
    root = os.path.realpath(workspace_root)
    resolved = os.path.realpath(project_path)
    try:
        common = os.path.commonpath([root, resolved])
    except ValueError:
        return False
    return common == root


async def run_command_in_workspace(
    cwd: str,
    command: str,
    *,
    workspace_root: str,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> str:
    """Run a shell command in cwd; cwd must lie under workspace_root (after realpath)."""
    cwd_resolved = os.path.realpath(cwd)
    if not os.path.isdir(cwd_resolved):
        return f"错误: 项目路径不存在: {cwd_resolved}"
    if not is_project_within_workspace(cwd_resolved, workspace_root):
        return "错误: 项目路径不在允许的工作区内"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd_resolved,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            return "错误: 命令执行超时 (30s)"

        output_parts: list[str] = []
        if stdout:
            output_parts.append(stdout.decode(errors="replace"))
        if stderr:
            output_parts.append(f"[stderr] {stderr.decode(errors='replace')}")

        result = "\n".join(output_parts) if output_parts else "(no output)"

        if proc.returncode != 0:
            result = f"[exit code: {proc.returncode}]\n{result}"

        return result[:MAX_OUTPUT_CHARS]

    except Exception as e:
        return f"错误: {e}"


def register_command_tools(agent: Agent) -> None:
    @agent.tool
    async def execute_command(
        ctx: RunContext[Any], command: str, project: str = ""
    ) -> str:
        """在项目目录中执行 shell 命令"""
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"

        if project:
            proj = pm.get_project(project)
        else:
            proj = pm.default_project

        if not proj:
            return (
                "错误: 未找到目标项目"
                if project
                else "错误: 未设置默认项目"
            )

        workspace_root = load_config().security.workspace_root
        return await run_command_in_workspace(
            proj.path,
            command,
            workspace_root=workspace_root,
            timeout=DEFAULT_COMMAND_TIMEOUT,
        )
