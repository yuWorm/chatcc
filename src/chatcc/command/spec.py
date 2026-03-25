from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RouteType(Enum):
    PASSTHROUGH = "passthrough"
    INTERCEPT = "intercept"
    AUGMENTED = "augmented"


@dataclass
class ParamDef:
    name: str
    required: bool = False
    default: str = ""
    description: str = ""


@dataclass
class CommandSpec:
    name: str
    description: str
    prompt_template: str = ""
    params: list[ParamDef] = field(default_factory=list)
    route_type: RouteType = RouteType.AUGMENTED
    category: str = "general"

    @property
    def slash_name(self) -> str:
        return f"/{self.name}"

    def build_prompt(self, parsed_args: dict[str, str]) -> str:
        """Fill prompt_template with parsed argument values."""
        if not self.prompt_template:
            return ""
        try:
            return self.prompt_template.format(**parsed_args)
        except KeyError:
            return self.prompt_template

    def parse_args(self, raw_args: list[str]) -> dict[str, str]:
        """Positional arg matching against declared params."""
        result: dict[str, str] = {}
        for i, param in enumerate(self.params):
            if i < len(raw_args):
                result[param.name] = raw_args[i]
            else:
                result[param.name] = param.default
        return result

    @property
    def usage(self) -> str:
        parts = [self.slash_name]
        for p in self.params:
            if p.required:
                parts.append(f"<{p.name}>")
            else:
                parts.append(f"[{p.name}]")
        return " ".join(parts)
