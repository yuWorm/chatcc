"""Setup UI abstraction — decouples interactive credential collection from presentation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import click


@runtime_checkable
class SetupUI(Protocol):
    """交互式配置收集的 UI 抽象。

    Channel 和 Provider 的 interactive_setup 通过此协议与用户交互，
    不直接依赖 click/终端，未来可替换为 TUI 或 Web UI。
    """

    def prompt(self, message: str, *, default: str = "", hide: bool = False) -> str:
        """提示用户输入"""
        ...

    def echo(self, message: str) -> None:
        """输出信息"""
        ...

    def choose(self, message: str, options: list[tuple[str, str]]) -> str:
        """选择题。options 为 [(value, label), ...]，返回选中的 value。"""
        ...

    def confirm(self, message: str, *, default: bool = False) -> bool:
        """是/否确认"""
        ...


class CliSetupUI:
    """基于 click 的 CLI 实现"""

    def prompt(self, message: str, *, default: str = "", hide: bool = False) -> str:
        if default != "":
            return click.prompt(message, default=default, hide_input=hide)
        return click.prompt(message, default="", hide_input=hide, show_default=False)

    def echo(self, message: str) -> None:
        click.echo(message)

    def choose(self, message: str, options: list[tuple[str, str]]) -> str:
        self.echo(message)
        for i, (value, label) in enumerate(options, 1):
            self.echo(f"  [{i}] {label}")

        while True:
            raw = click.prompt("请选择", type=int)
            if 1 <= raw <= len(options):
                return options[raw - 1][0]
            self.echo(f"  无效选择，请输入 1-{len(options)}")

    def confirm(self, message: str, *, default: bool = False) -> bool:
        return click.confirm(message, default=default)
