from __future__ import annotations

from chatcc.command.spec import CommandSpec, RouteType


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        self._commands[spec.name] = spec

    def register_many(self, specs: list[CommandSpec]) -> None:
        for spec in specs:
            self.register(spec)

    def get(self, name: str) -> CommandSpec | None:
        """Lookup by name (with or without leading slash)."""
        key = name.lstrip("/")
        return self._commands.get(key)

    def is_intercept(self, name: str) -> bool:
        spec = self.get(name)
        return spec is not None and spec.route_type == RouteType.INTERCEPT

    def is_augmented(self, name: str) -> bool:
        spec = self.get(name)
        return spec is not None and spec.route_type == RouteType.AUGMENTED

    @property
    def all_specs(self) -> list[CommandSpec]:
        return list(self._commands.values())

    @property
    def augmented_specs(self) -> list[CommandSpec]:
        return [s for s in self._commands.values() if s.route_type == RouteType.AUGMENTED]

    @property
    def intercept_specs(self) -> list[CommandSpec]:
        return [s for s in self._commands.values() if s.route_type == RouteType.INTERCEPT]

    def help_text(self) -> str:
        lines: list[str] = ["可用命令:"]
        by_category: dict[str, list[CommandSpec]] = {}
        for spec in self._commands.values():
            by_category.setdefault(spec.category, []).append(spec)

        for category, specs in by_category.items():
            lines.append(f"\n[{category}]")
            for spec in specs:
                lines.append(f"  {spec.usage}  — {spec.description}")

        return "\n".join(lines)
