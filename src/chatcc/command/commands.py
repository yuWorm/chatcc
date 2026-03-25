"""Built-in command definitions for ChatCC."""

from __future__ import annotations

from chatcc.command.spec import CommandSpec, ParamDef, RouteType


INTERCEPT_COMMANDS = [
    CommandSpec(
        name="y",
        description="确认待审批操作",
        params=[ParamDef("target", description="审批 ID 或 'all'")],
        route_type=RouteType.INTERCEPT,
        category="审批",
    ),
    CommandSpec(
        name="n",
        description="拒绝待审批操作",
        params=[ParamDef("target", description="审批 ID 或 'all'")],
        route_type=RouteType.INTERCEPT,
        category="审批",
    ),
    CommandSpec(
        name="pending",
        description="查看待审批列表",
        route_type=RouteType.INTERCEPT,
        category="审批",
    ),
]

AUGMENTED_COMMANDS = [
    CommandSpec(
        name="tasks",
        description="查看任务状态",
        params=[
            ParamDef("project", description="项目名称，留空则查看全部"),
        ],
        prompt_template=(
            "[命令] 用户请求查看任务状态。\n"
            "目标项目: {project}\n"
            "请调用 get_task_status 工具查询任务状态，并将结果简洁呈现给用户。"
            "如果项目参数为空，则展示所有项目的任务状态。"
        ),
        category="任务",
    ),
    CommandSpec(
        name="status",
        description="查看系统整体状态",
        prompt_template=(
            "[命令] 用户请求查看系统整体状态。\n"
            "请依次调用以下工具并汇总结果:\n"
            "1. list_projects — 获取项目列表\n"
            "2. get_task_status — 获取所有活跃任务状态\n"
            "将项目数量、活跃任务、待审批数等信息整合为简洁的状态报告。"
        ),
        category="系统",
    ),
    CommandSpec(
        name="session",
        description="查看项目会话信息",
        params=[
            ParamDef("project", description="项目名称，留空则用默认项目"),
            ParamDef("count", default="5", description="显示最近 N 条会话"),
        ],
        prompt_template=(
            "[命令] 用户请求查看会话信息。\n"
            "目标项目: {project}\n"
            "显示条数: {count}\n"
            "请调用 get_session_info 工具并将结果呈现给用户。"
        ),
        category="任务",
    ),
    CommandSpec(
        name="projects",
        description="列出所有项目",
        prompt_template=(
            "[命令] 用户请求查看项目列表。\n"
            "请调用 list_projects 工具，并将项目名称、路径、"
            "是否为默认项目等信息清晰呈现。"
        ),
        category="项目",
    ),
    CommandSpec(
        name="info",
        description="查看项目详情",
        params=[
            ParamDef("project", description="项目名称，留空则用默认项目"),
        ],
        prompt_template=(
            "[命令] 用户请求查看项目详情。\n"
            "目标项目: {project}\n"
            "请调用 get_project_info 工具获取项目信息并呈现。"
        ),
        category="项目",
    ),
    CommandSpec(
        name="new_session",
        description="为项目创建新会话",
        params=[
            ParamDef("project", description="项目名称，留空则用默认项目"),
        ],
        prompt_template=(
            "[命令] 用户请求为项目创建新的 Claude Code 会话。\n"
            "目标项目: {project}\n"
            "请调用 new_session 工具，关闭旧会话并创建新会话。"
        ),
        category="任务",
    ),
    CommandSpec(
        name="stop",
        description="中断当前任务",
        params=[
            ParamDef("project", description="项目名称，留空则用默认项目"),
        ],
        prompt_template=(
            "[命令] 用户请求中断当前正在执行的任务。\n"
            "目标项目: {project}\n"
            "请调用 interrupt_task 工具中断任务，并告知用户结果。"
        ),
        category="任务",
    ),
]

HELP_COMMAND = CommandSpec(
    name="help",
    description="查看所有可用命令",
    route_type=RouteType.INTERCEPT,
    category="系统",
)


def get_builtin_commands() -> list[CommandSpec]:
    return [*INTERCEPT_COMMANDS, *AUGMENTED_COMMANDS, HELP_COMMAND]
