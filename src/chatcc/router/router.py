from __future__ import annotations

from dataclasses import dataclass, field

from chatcc.channel.message import InboundMessage


@dataclass
class RouteResult:
    intercepted: bool
    command: str | None = None
    args: list[str] = field(default_factory=list)
    message: InboundMessage | None = None


class MessageRouter:
    INTERCEPT_COMMANDS = frozenset({"/y", "/n", "/pending", "/stop", "/status"})

    async def route(self, message: InboundMessage) -> RouteResult:
        parts = message.content.strip().split()
        if not parts:
            return RouteResult(intercepted=False, message=message)

        cmd = parts[0].lower()
        if cmd in self.INTERCEPT_COMMANDS:
            return RouteResult(
                intercepted=True,
                command=cmd,
                args=parts[1:],
            )

        return RouteResult(intercepted=False, message=message)
