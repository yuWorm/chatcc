import pytest
from chatcc.project.manager import ProjectManager


@pytest.fixture
def pm(tmp_path):
    return ProjectManager(data_dir=tmp_path / ".chatcc" / "projects")


def test_create_project(pm, tmp_path):
    proj_path = tmp_path / "myapp"
    proj_path.mkdir()
    project = pm.create_project("myapp", str(proj_path))
    assert project.name == "myapp"
    assert project.is_default is True


def test_first_project_is_default(pm, tmp_path):
    p1 = tmp_path / "proj1"
    p1.mkdir()
    proj1 = pm.create_project("proj1", str(p1))
    assert proj1.is_default is True

    p2 = tmp_path / "proj2"
    p2.mkdir()
    proj2 = pm.create_project("proj2", str(p2))
    assert proj2.is_default is False


def test_list_projects(pm, tmp_path):
    for name in ["a", "b", "c"]:
        p = tmp_path / name
        p.mkdir()
        pm.create_project(name, str(p))
    assert len(pm.list_projects()) == 3


def test_switch_default(pm, tmp_path):
    for name in ["a", "b"]:
        p = tmp_path / name
        p.mkdir()
        pm.create_project(name, str(p))

    pm.switch_default("b")
    assert pm.default_project.name == "b"


def test_duplicate_name_raises(pm, tmp_path):
    p = tmp_path / "dup"
    p.mkdir()
    pm.create_project("dup", str(p))
    with pytest.raises(ValueError, match="already exists"):
        pm.create_project("dup", str(p))


def test_delete_project(pm, tmp_path):
    p = tmp_path / "del"
    p.mkdir()
    pm.create_project("del", str(p))
    pm.delete_project("del")
    assert len(pm.list_projects()) == 0
