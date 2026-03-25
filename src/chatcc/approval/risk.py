from __future__ import annotations

import os
import re
from typing import Any, Literal


SAFE_TOOLS = frozenset({"Read", "Grep", "Glob", "LS", "ListDir"})

DANGEROUS_PATTERNS: dict[str, list[str]] = {
    "Bash": [r"\brm\s", r"\bsudo\b", r"\bcurl\b.*\|\s*bash"],
    "Write": [r"/etc/", r"/system/"],
}


def assess_risk(
    tool_name: str,
    input_data: dict[str, Any],
    workspace: str | None = None,
) -> Literal["safe", "dangerous", "forbidden"]:
    if workspace and _is_path_escape(input_data, workspace):
        return "forbidden"

    if tool_name in SAFE_TOOLS:
        return "safe"

    if tool_name in DANGEROUS_PATTERNS:
        input_str = str(input_data)
        for pattern in DANGEROUS_PATTERNS[tool_name]:
            if re.search(pattern, input_str):
                return "dangerous"

    return "safe"


def _is_path_escape(input_data: dict[str, Any], workspace: str) -> bool:
    for key in ("path", "file_path", "directory"):
        if key in input_data:
            resolved = os.path.realpath(str(input_data[key]))
            ws_resolved = os.path.realpath(workspace)
            if not resolved.startswith(ws_resolved):
                return True
    return False
