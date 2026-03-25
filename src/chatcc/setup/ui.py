"""Setup UI abstraction — decouples interactive credential collection from presentation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import questionary
from questionary import Style

_STYLE = Style([
    ("qmark", "fg:cyan bold"),
    ("question", "bold"),
    ("answer", "fg:green bold"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan bold"),
    ("selected", "fg:green"),
])


@runtime_checkable
class SetupUI(Protocol):
    """交互式配置收集的 UI 抽象。

    Channel 和 Provider 的 interactive_setup 通过此协议与用户交互，
    不直接依赖 click/终端，未来可替换为 TUI 或 Web UI。
    """

    def prompt(self, message: str, *, default: str = "", hide: bool = False) -> str:
        """提示用户输入"""
        ...

    def prompt_secret(self, message: str, *, has_existing: bool = False) -> str | None:
        """密钥输入。has_existing=True 时空输入返回 None 表示保留原值。"""
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
    """基于 questionary 的 CLI 实现"""

    def prompt(self, message: str, *, default: str = "", hide: bool = False) -> str:
        if hide:
            result = questionary.password(message, style=_STYLE).ask()
        else:
            result = questionary.text(message, default=default, style=_STYLE).ask()
        if result is None:
            raise KeyboardInterrupt
        return result

    def prompt_secret(self, message: str, *, has_existing: bool = False) -> str | None:
        suffix = " (回车保留当前)" if has_existing else ""
        result = questionary.password(f"{message}{suffix}", style=_STYLE).ask()
        if result is None:
            raise KeyboardInterrupt
        if not result and has_existing:
            return None
        return result

    def echo(self, message: str) -> None:
        questionary.print(message, style="bold")

    def choose(self, message: str, options: list[tuple[str, str]]) -> str:
        choices = [questionary.Choice(title=label, value=value) for value, label in options]
        result = questionary.select(message, choices=choices, style=_STYLE).ask()
        if result is None:
            raise KeyboardInterrupt
        return result

    def confirm(self, message: str, *, default: bool = False) -> bool:
        result = questionary.confirm(message, default=default, style=_STYLE).ask()
        if result is None:
            raise KeyboardInterrupt
        return result
