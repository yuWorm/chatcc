import asyncio
import sys
from pathlib import Path
from typing import Any

import click
import questionary
import yaml

from chatcc.config import CHATCC_HOME, AppConfig


@click.group()
def cli():
    """ChatCC - 通过 IM 控制 Claude Code"""
    pass


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _show_config_summary(config: AppConfig) -> None:
    questionary.print("  当前配置:", style="bold")
    ap = config.agent.active_provider
    provider = config.agent.providers.get(ap)
    if provider:
        masked = _mask_key(provider.api_key) if provider.api_key else "(未设置)"
        questionary.print(f"    AI Provider: {ap} / {provider.model}", style="fg:green")
        questionary.print(f"    API Key: {masked}", style="fg:green")
    else:
        questionary.print("    AI Provider: (未配置)", style="fg:yellow")

    ch = config.channel.type
    if ch != "cli":
        questionary.print(f"    IM 渠道: {ch}", style="fg:green")
    else:
        questionary.print("    IM 渠道: (未配置)", style="fg:yellow")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _update_config(updates: dict[str, Any], *, config_dir: Path | None = None) -> None:
    root = config_dir if config_dir is not None else CHATCC_HOME
    config_path = root / "config.yaml"
    root.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path) as f:
            existing = yaml.safe_load(f) or {}

    _deep_merge(existing, updates)

    with open(config_path, "w") as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)


# ---------------------------------------------------------------------------
# Channel auth — delegates to Channel.interactive_setup(ui)
# ---------------------------------------------------------------------------

def _run_channel_setup(
    channel_type: str,
    *,
    existing: dict[str, Any] | None = None,
    config_dir: Path | None = None,
) -> None:
    from chatcc.channel.factory import get_channel_class
    from chatcc.setup.ui import CliSetupUI

    if channel_type == "cli":
        questionary.print("CLI 渠道无需认证", style="fg:yellow")
        return

    cls = get_channel_class(channel_type)
    ui = CliSetupUI()

    try:
        channel_config = cls.interactive_setup(ui, existing=existing)
    except ValueError as e:
        questionary.print(f"错误: {e}", style="bold fg:red")
        return

    _update_config(
        {"channel": {"type": channel_type, channel_type: channel_config}},
        config_dir=config_dir,
    )

    ui.echo(f"✅ {channel_type} 认证完成")
    ui.echo("   运行 `chatcc run` 启动")


# ---------------------------------------------------------------------------
# Provider setup
# ---------------------------------------------------------------------------

PROVIDER_OPTIONS: list[tuple[str, str]] = [
    ("anthropic", "Anthropic (Claude)"),
    ("openai", "OpenAI Chat Completions (GPT)"),
    ("openai-responses", "OpenAI Responses API (GPT)"),
    ("google", "Google Gemini"),
    ("custom", "自定义 (OpenAI 兼容 API)"),
]

DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "openai-responses": "gpt-4o",
    "google": "gemini-2.5-pro",
}


def _run_provider_setup(
    *,
    existing: dict[str, Any] | None = None,
    config_dir: Path | None = None,
) -> None:
    from chatcc.config import ProviderConfig
    from chatcc.setup.ui import CliSetupUI

    ui = CliSetupUI()
    questionary.print("=== AI Provider 配置 ===", style="bold fg:cyan")

    ex = ProviderConfig(**(existing or {}))
    has_existing = existing is not None

    provider_name = ui.choose("选择 AI 供应商:", PROVIDER_OPTIONS)

    if provider_name == "custom":
        default_name = ex.name if has_existing and ex.name not in dict(PROVIDER_OPTIONS) else "custom-llm"
        provider_name = ui.prompt("供应商名称 (用于配置标识)", default=default_name)
        base_url = ui.prompt(
            "API Base URL (例: https://api.example.com/v1)",
            default=ex.base_url or "",
        )
        model = ui.prompt("模型名称", default=ex.model if has_existing else "")
        new_key = ui.prompt_secret("API Key", has_existing=has_existing)
        api_key = new_key if new_key is not None else ex.api_key

        provider_config: dict[str, Any] = {
            "name": provider_name,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
        }
    else:
        default_model = ex.model if has_existing and ex.name == provider_name else DEFAULT_MODELS.get(provider_name, "")
        model = ui.prompt("模型名称", default=default_model)
        keep_key = has_existing and ex.name == provider_name
        new_key = ui.prompt_secret("API Key", has_existing=keep_key)
        api_key = new_key if new_key is not None else ex.api_key

        provider_config = {
            "name": provider_name,
            "model": model,
            "api_key": api_key,
        }

    _update_config(
        {
            "agent": {
                "active_provider": provider_name,
                "providers": {provider_name: provider_config},
            }
        },
        config_dir=config_dir,
    )

    questionary.print(f"✅ Provider 配置完成: {provider_name} / {model}", style="bold fg:green")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option(
    "--channel",
    default=None,
    type=click.Choice(["cli", "telegram", "feishu", "wechat"], case_sensitive=False),
    help="覆盖配置文件中的 IM 渠道",
)
@click.option("--debug", is_flag=True, default=False)
def run(config_path: str | None, channel: str | None, debug: bool):
    """启动 ChatCC"""
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if debug else "INFO")

    from chatcc.config import load_config
    from chatcc.app import Application

    config = load_config(Path(config_path) if config_path else None)
    if channel:
        config.channel.type = channel
    asyncio.run(Application(config).start())


@cli.command()
@click.option("--channel", default=None, help="指定渠道 (telegram/feishu)")
def auth(channel: str | None) -> None:
    """渠道认证 — 配置 IM 渠道凭证"""
    from chatcc.channel.factory import CHANNEL_LABELS
    from chatcc.config import load_config
    from chatcc.setup.ui import CliSetupUI

    if channel:
        _run_channel_setup(channel)
        return

    config = load_config()
    if config.channel.type != "cli":
        _run_channel_setup(config.channel.type)
        return

    ui = CliSetupUI()
    ch_type = ui.choose("选择 IM 渠道:", CHANNEL_LABELS)
    _run_channel_setup(ch_type)


def _run_full_wizard() -> None:
    """完整初始化向导 (首次或 --reset)。"""
    from chatcc.channel.factory import CHANNEL_LABELS
    from chatcc.setup.ui import CliSetupUI

    ui = CliSetupUI()
    questionary.print("")
    questionary.print("╔════════════════════════════════════╗", style="bold fg:cyan")
    questionary.print("║     ChatCC 初始化向导               ║", style="bold fg:cyan")
    questionary.print("╚════════════════════════════════════╝", style="bold fg:cyan")
    questionary.print("")

    questionary.print("── Step 1/2: AI Provider ──", style="bold fg:yellow")
    questionary.print("")
    _run_provider_setup()

    questionary.print("")

    questionary.print("── Step 2/2: IM 渠道 ──", style="bold fg:yellow")
    questionary.print("")
    ch_type = ui.choose("选择 IM 渠道:", CHANNEL_LABELS)
    _run_channel_setup(ch_type)

    questionary.print("")
    questionary.print("═" * 38, style="bold fg:green")
    questionary.print("✅ ChatCC 初始化完成!", style="bold fg:green")
    questionary.print(f"   配置文件: {CHATCC_HOME / 'config.yaml'}", style="fg:green")
    questionary.print("   运行 `chatcc run` 启动", style="fg:green")
    questionary.print("═" * 38, style="bold fg:green")


INIT_MENU_OPTIONS: list[tuple[str, str]] = [
    ("provider", "修改 AI Provider"),
    ("channel", "修改 IM 渠道"),
    ("reinit", "重新初始化 (全部重新配置)"),
    ("exit", "完成退出"),
]


def _run_config_menu() -> None:
    """已有配置时的增量修改菜单。"""
    from chatcc.channel.factory import CHANNEL_LABELS
    from chatcc.config import load_config
    from chatcc.setup.ui import CliSetupUI

    ui = CliSetupUI()
    questionary.print("")
    questionary.print("╔════════════════════════════════════╗", style="bold fg:cyan")
    questionary.print("║     ChatCC 配置管理                 ║", style="bold fg:cyan")
    questionary.print("╚════════════════════════════════════╝", style="bold fg:cyan")

    while True:
        config = load_config()
        questionary.print("")
        _show_config_summary(config)
        questionary.print("")

        action = ui.choose("请选择操作:", INIT_MENU_OPTIONS)

        if action == "provider":
            questionary.print("")
            ap = config.agent.active_provider
            provider = config.agent.providers.get(ap)
            ex = None
            if provider:
                ex = {"name": provider.name, "model": provider.model, "api_key": provider.api_key}
                if provider.base_url:
                    ex["base_url"] = provider.base_url
            _run_provider_setup(existing=ex)

        elif action == "channel":
            questionary.print("")
            ch_type = config.channel.type
            existing_ch_config = getattr(config.channel, ch_type, {}) if ch_type != "cli" else {}

            if ch_type != "cli":
                sub = ui.choose("渠道操作:", [
                    ("reconfig", f"重新配置当前渠道 ({ch_type})"),
                    ("switch", "切换到其他渠道"),
                ])
                if sub == "reconfig":
                    _run_channel_setup(ch_type, existing=existing_ch_config)
                else:
                    new_type = ui.choose("选择 IM 渠道:", CHANNEL_LABELS)
                    _run_channel_setup(new_type)
            else:
                new_type = ui.choose("选择 IM 渠道:", CHANNEL_LABELS)
                _run_channel_setup(new_type)

        elif action == "reinit":
            questionary.print("")
            _run_full_wizard()
            break

        elif action == "exit":
            questionary.print("")
            questionary.print("✅ 配置已保存", style="bold fg:green")
            questionary.print(f"   配置文件: {CHATCC_HOME / 'config.yaml'}", style="fg:green")
            questionary.print("   运行 `chatcc run` 启动", style="fg:green")
            break


@cli.command(name="init")
@click.option("--reset", is_flag=True, default=False, help="忽略现有配置，完全重新初始化")
def init_cmd(reset: bool) -> None:
    """初始化向导 — 一站式配置 AI Provider 和 IM 渠道"""
    config_path = CHATCC_HOME / "config.yaml"
    has_config = config_path.exists() and config_path.stat().st_size > 0

    if reset or not has_config:
        _run_full_wizard()
    else:
        _run_config_menu()


if __name__ == "__main__":
    cli()
