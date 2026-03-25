from __future__ import annotations

from dataclasses import dataclass, field

from chatcc.channel.message import InboundMessage
from chatcc.command.registry import CommandRegistry
from chatcc.command.spec import CommandSpec, RouteType


@dataclass
class RouteResult:
    route_type: RouteType
    command: str | None = None
    args: list[str] = field(default_factory=list)
    parsed_args: dict[str, str] = field(default_factory=dict)
    augmented_prompt: str = ""
    message: InboundMessage | None = None
    spec: CommandSpec | None = None

    @property
    def intercepted(self) -> bool:
        return self.route_type == RouteType.INTERCEPT

    @property
    def augmented(self) -> bool:
        return self.route_type == RouteType.AUGMENTED


class MessageRouter:
    def __init__(self, registry: CommandRegistry | None = None) -> None:
        self._registry = registry or CommandRegistry()

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    async def route(self, message: InboundMessage) -> RouteResult:
        parts = message.content.strip().split()
        if not parts:
            return RouteResult(route_type=RouteType.PASSTHROUGH, message=message)

        cmd = parts[0].lower()
        if not cmd.startswith("/"):
            return RouteResult(route_type=RouteType.PASSTHROUGH, message=message)

        spec = self._registry.get(cmd)
        if spec is None:
            return RouteResult(route_type=RouteType.PASSTHROUGH, message=message)

        raw_args = parts[1:]
        parsed_args = spec.parse_args(raw_args)

        if spec.route_type == RouteType.INTERCEPT:
            return RouteResult(
                route_type=RouteType.INTERCEPT,
                command=cmd,
                args=raw_args,
                parsed_args=parsed_args,
                spec=spec,
            )

        augmented_prompt = spec.build_prompt(parsed_args)
        return RouteResult(
            route_type=RouteType.AUGMENTED,
            command=cmd,
            args=raw_args,
            parsed_args=parsed_args,
            augmented_prompt=augmented_prompt,
            message=message,
            spec=spec,
        )
