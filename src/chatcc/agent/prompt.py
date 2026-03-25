from __future__ import annotations

from datetime import datetime
from pathlib import Path


PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def load_persona(name: str = "default") -> str:
    path = PERSONAS_DIR / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_system_prompt(
    persona_name: str = "default",
    default_project: str | None = None,
    active_count: int = 0,
    pending_count: int = 0,
    memory_context: str = "",
) -> str:
    static = load_persona(persona_name)

    dynamic_lines = [
        f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"当前默认项目: {default_project or '未设置'}",
        f"活跃项目数: {active_count}",
        f"待确认操作: {pending_count}",
    ]
    dynamic = "\n".join(dynamic_lines)

    parts = [static, "\n---\n", dynamic]
    if memory_context:
        parts.extend(["\n---\n", memory_context])

    return "\n".join(parts)
