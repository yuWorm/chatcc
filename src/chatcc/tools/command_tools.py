from __future__ import annotations

import asyncio
import os
from typing import Any

from pydantic_ai import Agent, RunContext

DEFAULT_COMMAND_TIMEOUT = 30.0
MAX_OUTPUT_CHARS = 4000


def is_path_within(child: str, parent: str) -> bool:
    parent_resolved = os.path.realpath(parent)
    child_resolved = os.path.realpath(child)
    try:
        common = os.path.commonpath([parent_resolved, child_resolved])
    except ValueError:
        return False
    return common == parent_resolved


async def run_command_in_project(
    cwd: str,
    command: str,
    *,
    workspace: str,
    timeout: float = DEFAULT_COMMAND_TIMEOUT,
) -> str:
    """Run a shell command in project cwd; cwd must lie under workspace (after realpath)."""
    cwd_resolved = os.path.realpath(cwd)
    if not os.path.isdir(cwd_resolved):
        return f"错误: 项目路径不存在: {cwd_resolved}"
    if not is_path_within(cwd_resolved, workspace):
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

        return await run_command_in_project(
            proj.path,
            command,
            workspace=str(pm.workspace),
            timeout=DEFAULT_COMMAND_TIMEOUT,
        )
