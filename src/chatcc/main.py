import asyncio
import sys
from pathlib import Path
from typing import Any

import click
import questionary
import yaml

from chatcc.config import CHATCC_HOME


@click.group()
def cli():
    """ChatCC - 通过 IM 控制 Claude Code"""
    pass


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

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
        channel_config = cls.interactive_setup(ui)
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
    config_dir: Path | None = None,
) -> None:
    from chatcc.setup.ui import CliSetupUI

    ui = CliSetupUI()
    questionary.print("=== AI Provider 配置 ===", style="bold fg:cyan")

    provider_name = ui.choose("选择 AI 供应商:", PROVIDER_OPTIONS)
    default_model = DEFAULT_MODELS.get(provider_name, "")

    if provider_name == "custom":
        provider_name = ui.prompt("供应商名称 (用于配置标识)", default="custom-llm")
        base_url = ui.prompt("API Base URL (例: https://api.example.com/v1)")
        model = ui.prompt("模型名称")
        api_key = ui.prompt("API Key", hide=True)

        provider_config = {
            "name": provider_name,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
        }
    else:
        model = ui.prompt("模型名称", default=default_model)
        api_key = ui.prompt("API Key", hide=True)

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
@click.option("--debug", is_flag=True, default=False)
def run(config_path: str | None, debug: bool):
    """启动 ChatCC"""
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if debug else "INFO")

    from chatcc.config import load_config
    from chatcc.app import Application

    config = load_config(Path(config_path) if config_path else None)
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


@cli.command(name="init")
def init_cmd() -> None:
    """初始化向导 — 一站式配置 AI Provider 和 IM 渠道"""
    from chatcc.channel.factory import CHANNEL_LABELS
    from chatcc.setup.ui import CliSetupUI

    ui = CliSetupUI()
    questionary.print("")
    questionary.print("╔════════════════════════════════════╗", style="bold fg:cyan")
    questionary.print("║     ChatCC 初始化向导               ║", style="bold fg:cyan")
    questionary.print("╚════════════════════════════════════╝", style="bold fg:cyan")
    questionary.print("")

    # Step 1: AI Provider
    questionary.print("── Step 1/2: AI Provider ──", style="bold fg:yellow")
    questionary.print("")
    _run_provider_setup()

    questionary.print("")

    # Step 2: IM Channel
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


if __name__ == "__main__":
    cli()
