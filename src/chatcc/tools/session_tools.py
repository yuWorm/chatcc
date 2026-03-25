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
        """为项目创建新的 Claude Code 会话 (断开旧会话，记录关闭)"""
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

        old_sid = session.active_session_id
        tm.close_session(proj_name)
        await session.disconnect()
        session.active_session_id = None
        session.task_state = TaskState.IDLE

        msg = f"项目 '{proj_name}' 的 Claude Code 会话已重置"
        if old_sid:
            msg += f" (已关闭会话 {old_sid[:8]}…)"
        return msg

    @agent.tool
    def get_session_info(ctx: RunContext[Any], project: str = "", count: int = 5) -> str:
        """查看项目的 Claude Code 会话历史。显示当前活跃会话及最近 N 个已关闭会话。"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        session_log = tm.get_session_log(proj_name)
        if not session_log:
            return f"错误: 项目 '{proj_name}' 不存在"

        lines: list[str] = [f"[{proj_name}] 会话历史:"]

        active = session_log.active()
        if active:
            lines.append(
                f"  🟢 活跃: {active.session_id[:8]}… "
                f"| 任务数: {len(active.task_ids)} "
                f"| 花费: ${active.total_cost_usd:.4f} "
                f"| 开始: {active.started_at:%Y-%m-%d %H:%M}"
            )
        else:
            lines.append("  无活跃会话")

        records = session_log.latest(count)
        closed = [r for r in records if r.status == "closed"]
        if closed:
            lines.append(f"最近 {len(closed)} 个已关闭会话:")
            for r in reversed(closed):
                duration = ""
                if r.ended_at and r.started_at:
                    delta = r.ended_at - r.started_at
                    minutes = int(delta.total_seconds() / 60)
                    duration = f" | 时长: {minutes}m"
                lines.append(
                    f"  ⚪ {r.session_id[:8]}… "
                    f"| 任务数: {len(r.task_ids)} "
                    f"| 花费: ${r.total_cost_usd:.4f}{duration}"
                )
        elif not active:
            lines.append("暂无会话记录")

        return "\n".join(lines)


def _resolve_project_name(pm: Any, project: str) -> str | None:
    if project:
        proj = pm.get_project(project)
        return proj.name if proj else None
    dp = pm.default_project
    return dp.name if dp else None
