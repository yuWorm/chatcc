from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext


def register_service_tools(agent: Agent) -> None:
    @agent.tool
    async def start_service(
        ctx: RunContext[Any], name: str, command: str, project: str = ""
    ) -> str:
        """在项目目录中启动后台服务"""
        sm = ctx.deps.service_manager
        pm = ctx.deps.project_manager
        if not sm:
            return "错误: 服务管理器未初始化"
        if not pm:
            return "错误: 项目管理器未初始化"

        if project:
            proj = pm.get_project(project)
        else:
            proj = pm.default_project
        if not proj:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        try:
            svc = await sm.start(proj.name, name, command, cwd=proj.path)
            return f"服务 '{name}' 已启动 (PID: {svc.pid})"
        except ValueError as e:
            return f"启动失败: {e}"

    @agent.tool
    async def stop_service(
        ctx: RunContext[Any], name: str, project: str = ""
    ) -> str:
        """停止指定服务"""
        sm = ctx.deps.service_manager
        pm = ctx.deps.project_manager
        if not sm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目"

        result = await sm.stop(proj_name, name)
        if result:
            return f"服务 '{name}' 已停止"
        return f"服务 '{name}' 未找到或已停止"

    @agent.tool
    def service_status(ctx: RunContext[Any], project: str = "") -> str:
        """查看运行中的服务"""
        sm = ctx.deps.service_manager
        if not sm:
            return "错误: 服务管理器未初始化"

        proj = project if project else None
        services = sm.status(project=proj)
        if not services:
            return "暂无运行中的服务"
        lines = []
        for svc in services:
            lines.append(
                f"- [{svc.project}] {svc.name} (PID: {svc.pid}) — {svc.command}"
            )
        return "\n".join(lines)

    @agent.tool
    async def service_logs(
        ctx: RunContext[Any], name: str, lines: int = 50, project: str = ""
    ) -> str:
        """查看服务日志"""
        sm = ctx.deps.service_manager
        pm = ctx.deps.project_manager
        if not sm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目"

        return await sm.logs(proj_name, name, lines=lines)


def _resolve_project_name(pm: Any, project: str) -> str | None:
    if project:
        proj = pm.get_project(project)
        return proj.name if proj else None
    dp = pm.default_project
    return dp.name if dp else None
