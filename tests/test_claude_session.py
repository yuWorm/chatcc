from chatcc.claude.session import ProjectSession, TaskState
from chatcc.project.models import Project


def test_initial_state():
    project = Project(name="test", path="/tmp/test")
    session = ProjectSession(project)
    assert session.task_state == TaskState.IDLE
    assert session.client is None
    assert session.active_session_id is None


def test_task_state_enum():
    assert TaskState.IDLE.value == "idle"
    assert TaskState.RUNNING.value == "running"
    assert TaskState.COMPLETED.value == "completed"


def test_build_options():
    project = Project(name="test", path="/tmp/test")
    session = ProjectSession(project)
    options = session._build_options()
    assert str(options.cwd) == "/tmp/test"
    assert options.permission_mode == "acceptEdits"
