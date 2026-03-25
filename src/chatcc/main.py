import asyncio
import logging
from pathlib import Path
from typing import Any

import click
import yaml

from chatcc.config import CHATCC_HOME


@click.group()
def cli():
    """ChatCC - 通过 IM 控制 Claude Code"""
    pass


@cli.command()
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--debug", is_flag=True, default=False)
def run(config_path: str | None, debug: bool):
    """启动 ChatCC"""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from chatcc.config import load_config
    from chatcc.app import Application

    config = load_config(Path(config_path) if config_path else None)
    asyncio.run(Application(config).start())


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


def _auth_telegram() -> None:
    click.echo("=== Telegram Bot 认证 ===")
    token = click.prompt("请输入 Bot Token (从 @BotFather 获取)")

    if not token or ":" not in token:
        click.echo("错误: Token 格式无效 (应为 数字:字母串)")
        return

    allowed = click.prompt(
        "允许的用户 ID (逗号分隔, 留空允许所有)",
        default="",
    )

    allowed_list = [u.strip() for u in allowed.split(",") if u.strip()] if allowed else []

    _update_config({
        "channel": {
            "type": "telegram",
            "telegram": {
                "token": token,
                "allowed_users": allowed_list,
            },
        },
    })

    click.echo("✅ Telegram 认证完成")
    if allowed_list:
        click.echo(f"   允许用户: {', '.join(allowed_list)}")
    click.echo("   运行 `chatcc run` 启动")


def _auth_feishu() -> None:
    click.echo("=== 飞书应用认证 ===")
    app_id = click.prompt("请输入 App ID")
    app_secret = click.prompt("请输入 App Secret", hide_input=True)

    if not app_id or not app_secret:
        click.echo("错误: App ID 和 App Secret 不能为空")
        return

    allowed = click.prompt(
        "允许的用户 Open ID (逗号分隔, 留空允许所有)",
        default="",
    )

    allowed_list = [u.strip() for u in allowed.split(",") if u.strip()] if allowed else []

    _update_config({
        "channel": {
            "type": "feishu",
            "feishu": {
                "app_id": app_id,
                "app_secret": app_secret,
                "allowed_users": allowed_list,
            },
        },
    })

    click.echo("✅ 飞书认证完成")
    click.echo("   运行 `chatcc run` 启动")


@cli.command()
@click.option("--channel", default=None, help="指定渠道 (telegram/feishu)")
def auth(channel: str | None) -> None:
    """渠道认证 — 配置 IM 渠道凭证"""
    from chatcc.config import load_config

    config = load_config()
    ch_type = channel or config.channel.type

    match ch_type:
        case "telegram":
            _auth_telegram()
        case "feishu":
            _auth_feishu()
        case "cli":
            click.echo("CLI 渠道无需认证")
        case _:
            click.echo(f"未知渠道类型: {ch_type}")


if __name__ == "__main__":
    cli()
