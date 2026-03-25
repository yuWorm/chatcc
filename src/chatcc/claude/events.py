"""Hook routing helpers for Claude Code sessions."""


class SessionProjectMap:
    """session_id → project_name mapping for routing Claude Code hook callbacks"""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}

    def register(self, session_id: str, project_name: str) -> None:
        self._map[session_id] = project_name

    def get_project(self, session_id: str) -> str | None:
        return self._map.get(session_id)

    def unregister(self, session_id: str) -> None:
        self._map.pop(session_id, None)

    def clear(self) -> None:
        self._map.clear()
