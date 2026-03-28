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
