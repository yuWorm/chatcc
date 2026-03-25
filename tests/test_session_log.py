from __future__ import annotations

from datetime import datetime

import pytest

from chatcc.project.models import SessionRecord
from chatcc.project.session_log import SessionLog


@pytest.fixture
def session_log(tmp_path) -> SessionLog:
    return SessionLog(tmp_path / "sessions.jsonl")


def _make_record(
    session_id: str = "sess-abc",
    project_name: str = "proj",
    **kwargs,
) -> SessionRecord:
    return SessionRecord(session_id=session_id, project_name=project_name, **kwargs)


def test_append_and_get(session_log: SessionLog) -> None:
    sr = _make_record()
    session_log.append(sr)
    result = session_log.get("sess-abc")
    assert result is not None
    assert result.session_id == "sess-abc"
    assert result.status == "active"


def test_get_returns_none_for_missing(session_log: SessionLog) -> None:
    assert session_log.get("nonexistent") is None


def test_dedup_keeps_last_entry(session_log: SessionLog) -> None:
    sr1 = _make_record(task_ids=["t1"], total_cost_usd=0.01)
    session_log.append(sr1)

    sr2 = _make_record(task_ids=["t1", "t2"], total_cost_usd=0.05)
    session_log.append(sr2)

    result = session_log.get("sess-abc")
    assert result is not None
    assert result.task_ids == ["t1", "t2"]
    assert result.total_cost_usd == 0.05


def test_get_all(session_log: SessionLog) -> None:
    session_log.append(_make_record(session_id="s1"))
    session_log.append(_make_record(session_id="s2"))
    assert len(session_log.get_all()) == 2


def test_latest(session_log: SessionLog) -> None:
    for i in range(10):
        session_log.append(_make_record(session_id=f"s{i}"))
    result = session_log.latest(3)
    assert len(result) == 3


def test_active(session_log: SessionLog) -> None:
    session_log.append(_make_record(session_id="s1", status="closed"))
    session_log.append(_make_record(session_id="s2", status="active"))
    active = session_log.active()
    assert active is not None
    assert active.session_id == "s2"


def test_active_returns_none_when_all_closed(session_log: SessionLog) -> None:
    session_log.append(_make_record(session_id="s1", status="closed"))
    assert session_log.active() is None


def test_active_returns_none_for_empty_log(session_log: SessionLog) -> None:
    assert session_log.active() is None


def test_count(session_log: SessionLog) -> None:
    assert session_log.count() == 0
    session_log.append(_make_record(session_id="s1"))
    session_log.append(_make_record(session_id="s2"))
    assert session_log.count() == 2


def test_count_deduped(session_log: SessionLog) -> None:
    session_log.append(_make_record(session_id="s1", task_ids=["t1"]))
    session_log.append(_make_record(session_id="s1", task_ids=["t1", "t2"]))
    assert session_log.count() == 1


def test_malformed_lines_skipped(session_log: SessionLog) -> None:
    session_log._path.parent.mkdir(parents=True, exist_ok=True)
    with open(session_log._path, "w", encoding="utf-8") as f:
        f.write("not valid json\n")
        f.write('{"session_id":"s1","project_name":"p","started_at":"2025-01-01T00:00:00"}\n')
    assert session_log.count() == 1
    assert session_log.get("s1") is not None
