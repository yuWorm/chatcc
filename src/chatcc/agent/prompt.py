from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger

_BUNDLED_PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def ensure_personas(data_dir: Path) -> Path:
    """Ensure data_dir/personas/ exists, copying bundled defaults if missing."""
    personas_dir = data_dir / "personas"
    personas_dir.mkdir(parents=True, exist_ok=True)

    for src in _BUNDLED_PERSONAS_DIR.glob("*.md"):
        dst = personas_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
            logger.debug("Copied bundled persona '{}' to {}", src.stem, dst)

    return personas_dir


def load_persona(name: str = "default", *, personas_dir: Path | None = None) -> str:
    base = personas_dir if personas_dir is not None else _BUNDLED_PERSONAS_DIR
    path = base / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_system_prompt(
    persona_name: str = "default",
    default_project: str | None = None,
    active_count: int = 0,
    pending_count: int = 0,
    memory_context: str = "",
    personas_dir: Path | None = None,
) -> str:
    static = load_persona(persona_name, personas_dir=personas_dir)

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
