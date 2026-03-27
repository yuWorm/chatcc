from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CHATCC_HOME = Path(os.environ.get("CHATCC_HOME", str(Path.home() / ".chatcc")))


@dataclass
class ProviderConfig:
    name: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str | None = None
    type: str = "chat"  # "chat" or "responses" (OpenAI protocol only)


@dataclass
class AgentConfig:
    active_provider: str = "anthropic"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    persona: str = "default"
    memory: dict[str, Any] = field(default_factory=lambda: {
        "summarize_threshold": 50,
        "keep_recent": 10,
        "recent_daily_notes": 3,
    })


@dataclass
class ChannelConfig:
    type: str = "cli"
    telegram: dict[str, Any] = field(default_factory=dict)
    feishu: dict[str, Any] = field(default_factory=dict)
    wechat: dict[str, Any] = field(default_factory=dict)
    discord: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityConfig:
    dangerous_tool_patterns: dict[str, list[str]] = field(default_factory=lambda: {
        "Bash": [r"\brm\s", r"\bsudo\b", r"\bcurl\b.*\|\s*bash"],
        "Write": [r"/etc/", r"/system/"],
    })


@dataclass
class ClaudeDefaultsConfig:
    permission_mode: str = "acceptEdits"
    setting_sources: list[str] = field(default_factory=lambda: ["project"])
    model: str | None = None


@dataclass
class BudgetConfig:
    daily_limit: float | None = None


@dataclass
class SessionPolicyConfig:
    """Tuning knobs for per-project Claude Code session lifecycle."""

    max_tasks_per_session: int = 10
    max_cost_per_session: float = 2.0
    idle_disconnect_seconds: int = 300
    restore_on_startup: bool = True


@dataclass
class RichMessageConfig:
    """Controls rich-message formatting for outbound notifications."""

    parse_agent_markdown: bool = False

@dataclass
class AppConfig:
    data_dir: str = field(default_factory=lambda: str(CHATCC_HOME))
    workspace: str = field(default_factory=lambda: str(Path.home()))
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    claude_defaults: ClaudeDefaultsConfig = field(default_factory=ClaudeDefaultsConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    session_policy: SessionPolicyConfig = field(default_factory=SessionPolicyConfig)
    rich_message: RichMessageConfig = field(default_factory=RichMessageConfig)


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        def replacer(match: re.Match) -> str:
            return os.environ.get(match.group(1), match.group(0))
        return _ENV_VAR_PATTERN.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        path = CHATCC_HOME / "config.yaml"
    if not path.exists():
        return AppConfig()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    expanded = _expand_env_vars(raw)
    config = AppConfig()

    if "data_dir" in expanded:
        config.data_dir = str(Path(expanded["data_dir"]).expanduser().resolve())
    if "workspace" in expanded:
        config.workspace = str(Path(expanded["workspace"]).expanduser().resolve())

    if "channel" in expanded:
        ch = expanded["channel"]
        config.channel = ChannelConfig(
            type=ch.get("type", "cli"),
            telegram=ch.get("telegram", {}),
            feishu=ch.get("feishu", {}),
            wechat=ch.get("wechat", {}),
            discord=ch.get("discord", {}),
        )

    if "agent" in expanded:
        ag = expanded["agent"]
        providers = {}
        for name, pdata in ag.get("providers", {}).items():
            if isinstance(pdata, dict):
                providers[name] = ProviderConfig(**pdata)
        config.agent = AgentConfig(
            active_provider=ag.get("active_provider", "anthropic"),
            providers=providers,
            persona=ag.get("persona", "default"),
            memory=ag.get("memory", config.agent.memory),
        )

    if "security" in expanded:
        sec = expanded["security"]
        config.security = SecurityConfig(
            dangerous_tool_patterns=sec.get(
                "dangerous_tool_patterns", config.security.dangerous_tool_patterns
            ),
        )

    if "claude_defaults" in expanded:
        cd = expanded["claude_defaults"]
        config.claude_defaults = ClaudeDefaultsConfig(
            permission_mode=cd.get("permission_mode", "acceptEdits"),
            setting_sources=cd.get("setting_sources", ["project"]),
            model=cd.get("model"),
        )

    if "budget" in expanded:
        bd = expanded["budget"]
        config.budget = BudgetConfig(
            daily_limit=bd.get("daily_limit"),
        )

    if "session_policy" in expanded:
        sp = expanded["session_policy"]
        config.session_policy = SessionPolicyConfig(
            max_tasks_per_session=sp.get("max_tasks_per_session", 10),
            max_cost_per_session=sp.get("max_cost_per_session", 2.0),
            idle_disconnect_seconds=sp.get("idle_disconnect_seconds", 300),
            restore_on_startup=sp.get("restore_on_startup", True),
        )

    if "rich_message" in expanded:
        rm = expanded["rich_message"]
        config.rich_message = RichMessageConfig(
            parse_agent_markdown=rm.get("parse_agent_markdown", False),
        )

    return config
