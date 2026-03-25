import asyncio
import logging
from pathlib import Path

import click


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
    click.echo("ChatCC starting... (app not yet wired)")


@cli.command()
@click.option("--channel", default=None, help="指定渠道")
def auth(channel: str | None):
    """渠道认证"""
    click.echo(f"TODO: auth for channel={channel}")


if __name__ == "__main__":
    cli()
