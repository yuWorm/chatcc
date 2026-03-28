from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

from chatcc.service.manager import RunningService, ServiceManager


@pytest_asyncio.fixture
async def svc_manager(tmp_path: Path):
    mgr = ServiceManager(services_dir=tmp_path / "services")
    yield mgr
    await mgr.stop_all()


@pytest.mark.asyncio
async def test_start_service(svc_manager: ServiceManager, tmp_path: Path):
    svc = await svc_manager.start("proj", "sleeper", "sleep 60", cwd=str(tmp_path))
    assert isinstance(svc, RunningService)
    assert svc.pid > 0
    assert svc.name == "sleeper"


@pytest.mark.asyncio
async def test_stop_service(svc_manager: ServiceManager, tmp_path: Path):
    await svc_manager.start("proj", "sleeper", "sleep 60", cwd=str(tmp_path))
    result = await svc_manager.stop("proj", "sleeper")
    assert result is True


@pytest.mark.asyncio
async def test_start_duplicate_raises(svc_manager: ServiceManager, tmp_path: Path):
    await svc_manager.start("proj", "sleeper", "sleep 60", cwd=str(tmp_path))
    with pytest.raises(ValueError, match="already running"):
        await svc_manager.start("proj", "sleeper", "sleep 60", cwd=str(tmp_path))
    await svc_manager.stop("proj", "sleeper")


@pytest.mark.asyncio
async def test_status(svc_manager: ServiceManager, tmp_path: Path):
    await svc_manager.start("proj", "sleeper", "sleep 60", cwd=str(tmp_path))
    services = svc_manager.status()
    assert len(services) == 1
    assert services[0].name == "sleeper"
    await svc_manager.stop_all()


@pytest.mark.asyncio
async def test_logs(svc_manager: ServiceManager, tmp_path: Path):
    await svc_manager.start("proj", "echoer", "echo hello && sleep 1", cwd=str(tmp_path))
    await asyncio.sleep(0.5)
    log_output = await svc_manager.logs("proj", "echoer")
    assert "hello" in log_output
    await svc_manager.stop_all()


@pytest.mark.asyncio
async def test_stop_nonexistent(svc_manager: ServiceManager):
    result = await svc_manager.stop("proj", "nope")
    assert result is False


@pytest.mark.asyncio
async def test_stop_all(svc_manager: ServiceManager, tmp_path: Path):
    await svc_manager.start("proj", "s1", "sleep 60", cwd=str(tmp_path))
    await svc_manager.start("proj", "s2", "sleep 60", cwd=str(tmp_path))
    count = await svc_manager.stop_all()
    assert count == 2


def test_is_process_running_permission_error():
    """PermissionError means process exists but no permission — should return True."""
    with patch("os.kill", side_effect=PermissionError("not permitted")):
        assert ServiceManager._is_process_running(99999) is True


def test_is_process_running_not_found():
    with patch("os.kill", side_effect=ProcessLookupError()):
        assert ServiceManager._is_process_running(99999) is False


def test_is_process_running_ok():
    with patch("os.kill"):
        assert ServiceManager._is_process_running(99999) is True


@pytest.mark.asyncio
async def test_stop_kills_process_group(svc_manager: ServiceManager, tmp_path: Path):
    """stop() should kill the process group, not just the shell PID."""
    svc = await svc_manager.start(
        "proj", "nested", "sleep 60 & sleep 60 & wait", cwd=str(tmp_path)
    )
    pid = svc.pid
    pgid = os.getpgid(pid)
    assert pgid == pid  # start_new_session=True makes pid == pgid

    result = await svc_manager.stop("proj", "nested")
    assert result is True
    await asyncio.sleep(0.2)
    assert not ServiceManager._is_process_running(pid)
