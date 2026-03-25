from datetime import datetime
from chatcc.project.models import Project, ProjectConfig, SessionRecord


def test_project_creation():
    p = Project(name="myapp", path="/home/user/projects/myapp")
    assert p.name == "myapp"
    assert p.is_default is False
    assert isinstance(p.created_at, datetime)


def test_project_config_defaults():
    config = ProjectConfig()
    assert config.permission_mode == "acceptEdits"
    assert "project" in config.setting_sources


def test_session_record_defaults():
    sr = SessionRecord(session_id="sess-1", project_name="proj")
    assert sr.status == "active"
    assert sr.task_ids == []
    assert sr.total_cost_usd == 0.0
    assert sr.ended_at is None
    assert isinstance(sr.started_at, datetime)


def test_session_record_to_dict():
    sr = SessionRecord(
        session_id="sess-1",
        project_name="proj",
        task_ids=["t1", "t2"],
        total_cost_usd=0.123,
        status="closed",
    )
    d = sr.to_dict()
    assert d["session_id"] == "sess-1"
    assert d["project_name"] == "proj"
    assert d["task_ids"] == ["t1", "t2"]
    assert d["total_cost_usd"] == 0.123
    assert d["status"] == "closed"
    assert d["started_at"] is not None
    assert d["ended_at"] is None


def test_session_record_roundtrip():
    sr = SessionRecord(
        session_id="sess-x",
        project_name="proj",
        task_ids=["a", "b"],
        total_cost_usd=1.5,
        status="active",
    )
    d = sr.to_dict()
    restored = SessionRecord.from_dict(d)
    assert restored.session_id == sr.session_id
    assert restored.project_name == sr.project_name
    assert restored.task_ids == sr.task_ids
    assert restored.total_cost_usd == sr.total_cost_usd
    assert restored.status == sr.status
    assert restored.started_at == sr.started_at


def test_session_record_from_dict_defaults():
    d = {
        "session_id": "s1",
        "project_name": "p",
        "started_at": "2025-01-01T00:00:00",
    }
    sr = SessionRecord.from_dict(d)
    assert sr.task_ids == []
    assert sr.total_cost_usd == 0.0
    assert sr.status == "active"
    assert sr.ended_at is None
