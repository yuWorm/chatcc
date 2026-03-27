#!/usr/bin/env python3
"""手动测试 chatcc 会话恢复 + 发送任务的完整流程。

走 ProjectManager → TaskManager → SessionLog → submit_task 链路。

用法:
    uv run python scripts/test_resume_session.py
"""

import asyncio
import sys

from loguru import logger

from chatcc.claude.session import TaskState
from chatcc.claude.task_manager import TaskManager
from chatcc.config import SessionPolicyConfig
from chatcc.project.manager import ProjectManager
from chatcc.project.session_log import SessionLog


logger.remove()
logger.add(sys.stderr, level="DEBUG", format="{time:HH:mm:ss} | {level:<7} | {message}")


def pick(prompt: str, options: list[str]) -> int:
    print(f"\n{prompt}")
    for i, opt in enumerate(options):
        print(f"  [{i}] {opt}")
    while True:
        raw = input("\n请输入编号 (q 退出): ").strip()
        if raw.lower() == "q":
            sys.exit(0)
        try:
            idx = int(raw)
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass
        print("无效输入")


def show_divider(title: str):
    print(f"\n{'─' * 20} {title} {'─' * 20}")


async def main():
    # ── 1. 初始化 ProjectManager（和 chatcc app 一样从 ~/.chatcc 读取） ──
    show_divider("初始化")
    pm = ProjectManager()
    projects = pm.list_projects()

    if not projects:
        print("❌ 无项目，请先通过 chatcc 创建项目")
        return

    labels = []
    for p in projects:
        default = " ⭐" if p.is_default else ""
        labels.append(f"{p.name}{default} | path={p.path}")
    idx = pick("选择项目:", labels)
    project = projects[idx]
    print(f"\n✅ 选中: {project.name} → {project.path}")

    # ── 2. 查看 chatcc 的 sessions.jsonl 记录 ──
    show_divider("chatcc 会话记录 (sessions.jsonl)")
    data_dir = pm.project_dir(project.name)
    if data_dir:
        sl = SessionLog(data_dir / "sessions.jsonl")
        active = sl.active()
        if active:
            print(f"  🟢 活跃: {active.session_id[:12]}… | 任务数={len(active.task_ids)} | cost=${active.total_cost_usd:.4f}")
        else:
            print("  无活跃会话")

        recent = sl.latest(5)
        closed = [r for r in recent if r.status == "closed"]
        if closed:
            print(f"  最近 {len(closed)} 个已关闭会话:")
            for r in reversed(closed):
                print(f"    ⚪ {r.session_id[:12]}… | 任务数={len(r.task_ids)} | cost=${r.total_cost_usd:.4f}")
    else:
        print("  无数据目录")

    # ── 3. 查看 Claude Code 的会话列表（SDK 直读磁盘）──
    show_divider("Claude Code 会话 (SDK list_sessions)")
    try:
        from claude_agent_sdk import list_sessions, get_session_messages

        sdk_sessions = list_sessions(directory=project.path, limit=10)
        if not sdk_sessions:
            print("  该项目在 Claude Code 中无会话记录")
        else:
            for i, s in enumerate(sdk_sessions):
                summary = (s.summary or "(无摘要)")[:60]
                marker = " 👈 chatcc活跃" if (active and s.session_id == active.session_id) else ""
                print(f"  [{i}] {s.session_id[:12]}… | {summary}{marker}")
    except Exception as e:
        print(f"  获取失败: {e}")
        sdk_sessions = []

    # ── 4. 初始化 TaskManager，模拟 chatcc 启动时的恢复 ──
    show_divider("初始化 TaskManager (模拟 chatcc 启动)")

    notified: list[str] = []

    async def on_notify(proj: str, msg: str):
        notified.append(msg)
        print(f"  📢 [{proj}] {msg}")

    tm = TaskManager(
        project_manager=pm,
        on_notify=on_notify,
        session_policy=SessionPolicyConfig(
            idle_disconnect_seconds=600,
            max_tasks_per_session=50,
            max_cost_per_session=10.0,
        ),
    )

    session = tm.get_session(project.name)
    if not session:
        print("❌ get_session 失败")
        return

    print(f"  active_session_id = {session.active_session_id or '(None, 将创建新会话)'}")
    print(f"  task_state = {session.task_state.value}")
    print(f"  client = {'已连接' if session.client else '未连接'}")

    # ── 5. 可选：手动选择恢复其他会话 ──
    if sdk_sessions:
        switch = input("\n要切换到其他 Claude Code 会话吗？(y/n，直接回车保持当前): ").strip().lower()
        if switch == "y":
            idx = pick("选择要恢复的会话:", [
                f"{s.session_id[:12]}… | {(s.summary or '(无摘要)')[:50]}"
                for s in sdk_sessions
            ])
            new_sid = sdk_sessions[idx].session_id
            old_sid = session.active_session_id

            if old_sid:
                tm.close_session(project.name)
            try:
                await session.disconnect()
            except Exception:
                pass
            session.active_session_id = new_sid
            session.task_state = TaskState.IDLE

            print(f"  ✅ 已切换: {old_sid and old_sid[:12] or 'None'} → {new_sid[:12]}…")

    # ── 6. 发送任务 ──
    show_divider("发送任务")
    print(f"  当前 session_id = {session.active_session_id or '(新会话)'}")
    print(f"  cwd = {project.path}")

    while True:
        prompt = input("\n💬 输入任务 (q 退出): ").strip()
        if not prompt or prompt.lower() == "q":
            break

        print("⏳ 提交中...")
        result = await tm.submit_task(project.name, prompt)
        print(f"  submit_task → status={result.status} | {result.message}")

        if result.status in ("submitted", "queued"):
            print("⏳ 等待完成...")
            for _ in range(600):
                await asyncio.sleep(1)
                status = tm.get_task_status(project.name)
                state = session.task_state

                if state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.INTERRUPTED):
                    print(f"\n  ✅ 任务结束: state={state.value}")
                    break

                if _ % 10 == 9:
                    print(f"  ... {status}")
            else:
                print("  ⏰ 超时 (10分钟)")

            if notified:
                print("  通知记录:")
                for n in notified:
                    print(f"    {n}")
                notified.clear()

            print(f"  session_id = {session.active_session_id or '(None)'}")
            print(f"  client = {'已连接' if session.client else '未连接'}")

            task_log = tm.get_task_log(project.name)
            if task_log:
                records = task_log.latest(1)
                if records:
                    r = records[0]
                    print(f"  最新任务: #{r.id} [{r.status}] cost=${r.cost_usd:.4f} session={r.session_id and r.session_id[:12] or 'N/A'}")
                    if r.error:
                        print(f"  错误: {r.error}")

    # ── 7. 清理 ──
    show_divider("清理")
    await tm.shutdown()
    print("👋 已退出")


if __name__ == "__main__":
    asyncio.run(main())
