from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from chatcc.claude.session import TaskState


def register_session_tools(agent: Agent) -> None:
    @agent.tool
    async def send_to_claude(ctx: RunContext[Any], prompt: str, project: str = "") -> str:
        """将开发指令发送到目标项目的 Claude Code 会话"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm:
            return "错误: 任务管理器未初始化"
        if not pm:
            return "错误: 项目管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        return await tm.submit_task(proj_name, prompt)

    @agent.tool
    def get_task_status(ctx: RunContext[Any], project: str = "", history: int = 0) -> str:
        """获取项目的 Claude Code 任务状态。设置 history > 0 可查看最近 N 条历史任务。"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        if not project:
            all_status = tm.get_all_status()
            if not all_status:
                return "暂无活跃的 Claude Code 会话"
            lines = [f"- {name}: {status}" for name, status in all_status.items()]
            return "\n".join(lines)

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目"

        proj = pm.get_project(proj_name)
        lines = [f"[{proj_name}] 状态: {tm.get_task_status(proj_name)}"]

        if proj and proj.current_task:
            t = proj.current_task
            lines.append(f"  当前任务 #{t.id}: {t.prompt[:80]}")

        if history > 0:
            task_log = tm.get_task_log(proj_name)
            if task_log:
                records = task_log.latest(history)
                if records:
                    lines.append(f"最近 {len(records)} 条历史:")
                    for r in reversed(records):
                        cost = f"${r.cost_usd:.4f}" if r.cost_usd else ""
                        err = f" | {r.error[:60]}" if r.error else ""
                        lines.append(
                            f"  #{r.id} [{r.status}] {r.prompt[:60]} {cost}{err}"
                        )
                else:
                    lines.append("暂无历史任务记录")

        return "\n".join(lines)

    @agent.tool
    async def interrupt_task(ctx: RunContext[Any], project: str = "") -> str:
        """中断项目当前正在执行的 Claude Code 任务"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        return await tm.interrupt_task(proj_name)

    @agent.tool
    async def new_session(ctx: RunContext[Any], project: str = "") -> str:
        """为项目创建新的 Claude Code 会话 (断开旧会话)"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        session = tm.get_session(proj_name)
        if not session:
            return f"错误: 项目 '{proj_name}' 不存在"

        await session.disconnect()
        session.active_session_id = None
        session.task_state = TaskState.IDLE
        return f"项目 '{proj_name}' 的 Claude Code 会话已重置"


def _resolve_project_name(pm: Any, project: str) -> str | None:
    if project:
        proj = pm.get_project(project)
        return proj.name if proj else None
    dp = pm.default_project
    return dp.name if dp else None
