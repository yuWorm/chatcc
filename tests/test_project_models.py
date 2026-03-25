from datetime import datetime
from chatcc.project.models import Project, ProjectConfig


def test_project_creation():
    p = Project(name="myapp", path="/home/user/projects/myapp")
    assert p.name == "myapp"
    assert p.is_default is False
    assert isinstance(p.created_at, datetime)


def test_project_config_defaults():
    config = ProjectConfig()
    assert config.permission_mode == "acceptEdits"
    assert "project" in config.setting_sources
