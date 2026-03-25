from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext


def register_project_tools(agent: Agent) -> None:
    @agent.tool
    def create_project(ctx: RunContext[Any], name: str, path: str) -> str:
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"
        try:
            pm.create_project(name, path)
            return f"项目 '{name}' 创建成功 (路径: {path})"
        except ValueError as e:
            return f"创建失败: {e}"

    @agent.tool
    def list_projects(ctx: RunContext[Any]) -> str:
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"
        projects = pm.list_projects()
        if not projects:
            return "暂无项目"
        lines = []
        for p in projects:
            marker = " ⭐" if p.is_default else ""
            lines.append(f"- {p.name} ({p.path}){marker}")
        return "\n".join(lines)

    @agent.tool
    def switch_project(ctx: RunContext[Any], name: str) -> str:
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"
        try:
            pm.switch_default(name)
            return f"已切换默认项目为 '{name}'"
        except ValueError as e:
            return f"切换失败: {e}"

    @agent.tool
    def get_project_info(ctx: RunContext[Any], name: str = "") -> str:
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"
        if name == "":
            p = pm.default_project
            if not p:
                return "未设置默认项目"
        else:
            p = pm.get_project(name)
            if not p:
                return f"未找到项目 '{name}'"
        lines = [
            f"名称: {p.name}",
            f"路径: {p.path}",
            f"默认: {'是' if p.is_default else '否'}",
            f"创建时间: {p.created_at.isoformat()}",
        ]
        if p.config.model:
            lines.append(f"模型: {p.config.model}")
        return "\n".join(lines)

    @agent.tool
    def delete_project(ctx: RunContext[Any], name: str) -> str:
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"
        try:
            pm.delete_project(name)
            return f"项目 '{name}' 已归档"
        except ValueError as e:
            return f"归档失败: {e}"
