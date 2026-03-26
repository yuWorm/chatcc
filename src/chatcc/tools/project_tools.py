from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext


def register_project_tools(agent: Agent) -> None:
    @agent.tool
    def create_project(ctx: RunContext[Any], name: str, path: str = "") -> str:
        """创建项目。path 为空则使用默认路径 workspace/projects/<name>。"""
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"
        try:
            proj = pm.create_project(name, path or None)
            return f"项目 '{name}' 创建成功 (路径: {proj.path})"
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
        """查看项目详细信息，包含完整配置。不传 name 则查看默认项目。"""
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
            f"权限模式: {p.config.permission_mode}",
            f"配置源: {', '.join(p.config.setting_sources)}",
            f"模型: {p.config.model or '(默认)'}",
        ]
        return "\n".join(lines)

    @agent.tool
    def update_project_config(
        ctx: RunContext[Any],
        name: str = "",
        model: str = "",
        permission_mode: str = "",
        setting_sources: str = "",
    ) -> str:
        """修改项目配置。不传 name 则修改默认项目。
        setting_sources 用逗号分隔，如 'project,user'。
        传空字符串的字段不会被修改。"""
        pm = ctx.deps.project_manager
        if not pm:
            return "错误: 项目管理器未初始化"

        if not name:
            dp = pm.default_project
            if not dp:
                return "错误: 未设置默认项目"
            name = dp.name

        kwargs: dict = {}
        if model:
            kwargs["model"] = model
        if permission_mode:
            kwargs["permission_mode"] = permission_mode
        if setting_sources:
            kwargs["setting_sources"] = [s.strip() for s in setting_sources.split(",")]

        if not kwargs:
            return "未指定任何要修改的配置项"

        try:
            project = pm.update_config(name, **kwargs)
        except ValueError as e:
            return f"修改失败: {e}"

        changed = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        return f"项目 '{project.name}' 配置已更新: {changed}"

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
