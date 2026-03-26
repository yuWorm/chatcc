from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext

from chatcc.claude.session import TaskState

MAX_TEXT_PER_MSG = 300
MAX_MESSAGES = 20


def _extract_text(message: Any) -> str:
    """Extract displayable text from a SessionMessage.message field."""
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        parts.append(f"[tool: {block.get('name', '?')}]")
                    elif block.get("type") == "tool_result":
                        parts.append("[tool_result]")
            return "\n".join(parts) if parts else str(content)[:200]
    return str(message)[:200]


def _truncate(text: str, limit: int = MAX_TEXT_PER_MSG) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


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


    @agent.tool
    def session_dashboard(ctx: RunContext[Any]) -> str:
        """跨项目会话仪表盘：显示所有项目的 SDK 连接状态、任务状态、活跃会话和累计统计。"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        projects = pm.list_projects()
        if not projects:
            return "暂无项目"

        lines: list[str] = ["=== Claude Code 会话仪表盘 ==="]
        total_cost = 0.0
        total_tasks = 0

        for proj in projects:
            name = proj.name
            marker = " ⭐" if proj.is_default else ""
            session = tm.get_session(name)

            connected = "🟢 已连接" if (session and session.client) else "⚪ 未连接"
            state = session.task_state.value if session else "idle"

            current_info = ""
            if session and proj.current_task:
                t = proj.current_task
                current_info = f"\n    当前任务: #{t.id} {t.prompt[:60]}"

            session_id_str = ""
            if session and session.active_session_id:
                session_id_str = f" | 会话: {session.active_session_id[:8]}…"

            session_log = tm.get_session_log(name)
            task_log = tm.get_task_log(name)
            session_count = session_log.count() if session_log else 0
            task_count = task_log.count() if task_log else 0
            total_tasks += task_count

            cost_str = ""
            if session_log:
                active_rec = session_log.active()
                if active_rec:
                    total_cost += active_rec.total_cost_usd
                    cost_str = f" | 当前会话花费: ${active_rec.total_cost_usd:.4f}"

            lines.append(
                f"\n[{name}]{marker}\n"
                f"  连接: {connected} | 状态: {state}{session_id_str}\n"
                f"  累计: {task_count} 任务 / {session_count} 会话{cost_str}"
                f"{current_info}"
            )

        lines.append(f"\n--- 全局: {len(projects)} 个项目 | {total_tasks} 任务 | 花费 ${total_cost:.4f} ---")
        return "\n".join(lines)

    @agent.tool
    def get_task_history(
        ctx: RunContext[Any],
        project: str = "",
        count: int = 10,
        status: str = "",
    ) -> str:
        """查看项目的详细任务历史记录。可按 status (completed/failed/cancelled) 过滤。"""
        tm = ctx.deps.task_manager
        pm = ctx.deps.project_manager
        if not tm or not pm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        task_log = tm.get_task_log(proj_name)
        if not task_log:
            return f"错误: 项目 '{proj_name}' 不存在"

        total = task_log.count()
        records = task_log.latest(max(count, total))
        if status:
            records = [r for r in records if r.status == status]
        records = records[-count:]

        if not records:
            filter_hint = f" (过滤: {status})" if status else ""
            return f"[{proj_name}] 暂无任务记录{filter_hint}"

        lines: list[str] = [f"[{proj_name}] 任务历史 ({len(records)}/{total}):"]
        for r in reversed(records):
            cost = f"${r.cost_usd:.4f}" if r.cost_usd else "-"
            err = f"\n    错误: {r.error[:80]}" if r.error else ""
            sid = f" | 会话: {r.session_id[:8]}…" if r.session_id else ""
            duration = ""
            if r.completed_at and r.submitted_at:
                delta = r.completed_at - r.submitted_at
                secs = int(delta.total_seconds())
                if secs >= 60:
                    duration = f" | 耗时: {secs // 60}m{secs % 60}s"
                else:
                    duration = f" | 耗时: {secs}s"

            lines.append(
                f"  #{r.id} [{r.status}] {r.submitted_at:%m-%d %H:%M}\n"
                f"    {r.prompt[:100]}\n"
                f"    花费: {cost}{duration}{sid}{err}"
            )

        return "\n".join(lines)


    @agent.tool
    def get_session_messages(
        ctx: RunContext[Any],
        project: str = "",
        session_id: str = "",
        count: int = 10,
    ) -> str:
        """查询 Claude Code 会话的最近消息内容。

        不指定 session_id 时使用当前活跃会话或最近一个会话。
        count 控制获取的消息条数（默认 10，最大 20）。
        """
        from claude_agent_sdk import list_sessions
        from claude_agent_sdk import get_session_messages as sdk_get_messages

        pm = ctx.deps.project_manager
        tm = ctx.deps.task_manager
        if not pm or not tm:
            return "错误: 管理器未初始化"

        proj_name = _resolve_project_name(pm, project)
        if not proj_name:
            return "错误: 未找到目标项目" if project else "错误: 未设置默认项目"

        proj = pm.get_project(proj_name)
        if not proj:
            return f"错误: 项目 '{proj_name}' 不存在"

        count = min(count, MAX_MESSAGES)

        sid = session_id
        if not sid:
            session = tm.get_session(proj_name)
            if session and session.active_session_id:
                sid = session.active_session_id

        if not sid:
            sessions = list_sessions(directory=proj.path, limit=1)
            if sessions:
                sid = sessions[0].session_id

        if not sid:
            return f"[{proj_name}] 未找到任何 Claude Code 会话"

        try:
            messages = sdk_get_messages(sid, directory=proj.path, limit=count)
        except Exception as e:
            return f"错误: 获取会话消息失败 — {e}"

        if not messages:
            return f"[{proj_name}] 会话 {sid[:8]}… 暂无消息"

        lines: list[str] = [f"[{proj_name}] 会话 {sid[:8]}… 最近 {len(messages)} 条消息:"]
        for msg in messages:
            role = "👤" if msg.type == "user" else "🤖"
            text = _truncate(_extract_text(msg.message))
            lines.append(f"\n{role}  {text}")

        return "\n".join(lines)


def _resolve_project_name(pm: Any, project: str) -> str | None:
    if project:
        proj = pm.get_project(project)
        return proj.name if proj else None
    dp = pm.default_project
    return dp.name if dp else None
