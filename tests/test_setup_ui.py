"""Tests for SetupUI protocol and CliSetupUI."""

from __future__ import annotations

from chatcc.setup.ui import CliSetupUI, SetupUI


def test_cli_setup_ui_is_setup_ui():
    assert isinstance(CliSetupUI(), SetupUI)


class FakeSetupUI:
    """Deterministic test double for SetupUI."""

    def __init__(self, answers: list[str], confirms: list[bool] | None = None):
        self._answers = list(answers)
        self._confirms = list(confirms or [])
        self.echoed: list[str] = []

    def prompt(self, message: str, *, default: str = "", hide: bool = False) -> str:
        if self._answers:
            return self._answers.pop(0)
        return default

    def prompt_secret(self, message: str, *, has_existing: bool = False) -> str | None:
        if self._answers:
            val = self._answers.pop(0)
            if not val and has_existing:
                return None
            return val
        return "" if not has_existing else None

    def echo(self, message: str) -> None:
        self.echoed.append(message)

    def choose(self, message: str, options: list[tuple[str, str]]) -> str:
        idx = int(self._answers.pop(0)) - 1
        return options[idx][0]

    def confirm(self, message: str, *, default: bool = False) -> bool:
        if self._confirms:
            return self._confirms.pop(0)
        return default


def test_fake_setup_ui_protocol_conformance():
    assert isinstance(FakeSetupUI([]), SetupUI)


def test_fake_setup_ui_prompt():
    ui = FakeSetupUI(["hello"])
    assert ui.prompt("test") == "hello"


def test_fake_setup_ui_choose():
    ui = FakeSetupUI(["2"])
    result = ui.choose("pick", [("a", "A"), ("b", "B")])
    assert result == "b"


def test_fake_setup_ui_echo():
    ui = FakeSetupUI([])
    ui.echo("hi")
    assert ui.echoed == ["hi"]
