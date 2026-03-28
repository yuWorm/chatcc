from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatcc.service.detector import CommandEntry, ProjectDetector, ProjectProfile


@pytest.fixture
def detector() -> ProjectDetector:
    return ProjectDetector()


def test_detect_node_project(detector: ProjectDetector, tmp_path: Path):
    pkg = {
        "name": "test-app",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "test": "vitest",
            "lint": "eslint .",
        },
    }
    (tmp_path / "package.json").write_text(json.dumps(pkg))

    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "node"
    names = [c.name for c in profile.available_commands]
    assert "dev" in names
    assert "build" in names
    cmd = next(c for c in profile.available_commands if c.name == "dev")
    assert cmd.command == "npm run dev"
    assert cmd.source == "package.json"


def test_detect_unknown_project(detector: ProjectDetector, tmp_path: Path):
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "unknown"
    assert profile.available_commands == []


def test_detect_python_pyproject(detector: ProjectDetector, tmp_path: Path):
    toml_content = """
[project]
name = "myapp"

[project.scripts]
serve = "uvicorn myapp:app"
migrate = "alembic upgrade head"
"""
    (tmp_path / "pyproject.toml").write_text(toml_content)
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "python"
    names = [c.name for c in profile.available_commands]
    assert "serve" in names
    assert "migrate" in names


def test_detect_python_requirements_only(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("flask==3.0\n")
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "python"
    assert profile.available_commands == []


def test_detect_makefile(detector: ProjectDetector, tmp_path: Path):
    makefile = "build:\n\tgo build .\n\ntest:\n\tgo test ./...\n\nrun:\n\t./app\n"
    (tmp_path / "Makefile").write_text(makefile)
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "makefile"
    names = [c.name for c in profile.available_commands]
    assert "build" in names
    assert "test" in names
    assert "run" in names


def test_detect_go_with_cmd_dir(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/app\n\ngo 1.22\n")
    cmd_dir = tmp_path / "cmd" / "server"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "main.go").write_text("package main\n")
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "go"
    cmds = {c.name: c.command for c in profile.available_commands}
    assert cmds["server"] == "go run ./cmd/server"


def test_detect_go_with_main(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "go.mod").write_text("module example.com/app\n\ngo 1.22\n")
    (tmp_path / "main.go").write_text("package main\n")
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "go"
    assert any(c.command == "go run ." for c in profile.available_commands)


def test_detect_rust(detector: ProjectDetector, tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"\nversion = "0.1.0"\n')
    profile = detector.detect(str(tmp_path))
    assert profile.project_type == "rust"
    names = [c.name for c in profile.available_commands]
    assert "run" in names
    assert "build" in names
    assert "test" in names
