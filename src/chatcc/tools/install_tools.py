from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from chatcc.project.manager import ProjectManager


def register_install_tools(agent: Agent) -> None:
    @agent.tool
    async def install_skill(ctx: RunContext[Any], skill_url: str, project: str = "") -> str:
        """为项目的 Claude Code 安装 skill"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        install_prompt = f"请安装以下 skill: {skill_url}"
        result = await tm.submit_task(proj_name, install_prompt)

        if "已提交" in result:
            return f"Skill 安装指令已发送到项目 '{proj_name}': {skill_url}"
        return result

    @agent.tool
    async def install_mcp(
        ctx: RunContext[Any],
        name: str,
        command: str,
        args: str = "",
        project: str = "",
    ) -> str:
        """为项目的 Claude Code 配置 MCP server"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        if args:
            install_prompt = (
                f"请配置以下 MCP server:\n"
                f"名称: {name}\n"
                f"命令: {command}\n"
                f"参数: {args}"
            )
        else:
            install_prompt = (
                f"请配置以下 MCP server:\n"
                f"名称: {name}\n"
                f"命令: {command}"
            )

        result = await tm.submit_task(proj_name, install_prompt)

        if "已提交" in result:
            return f"MCP server '{name}' 配置指令已发送到项目 '{proj_name}'"
        return result


def _resolve_project_name(pm: ProjectManager, project: str) -> str | None:
    if project:
        proj = pm.get_project(project)
        return proj.name if proj else None
    dp = pm.default_project
    return dp.name if dp else None
