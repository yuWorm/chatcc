from chatcc.memory.longterm import LongTermMemory


def test_read_empty_memory(tmp_path):
    memory = LongTermMemory(memory_dir=tmp_path / "memory")
    content = memory.read_core()
    assert content == ""


def test_write_and_read_core(tmp_path):
    memory = LongTermMemory(memory_dir=tmp_path / "memory")
    memory.write_core("用户偏好: 中文回复")
    content = memory.read_core()
    assert "中文回复" in content


def test_append_daily_note(tmp_path):
    memory = LongTermMemory(memory_dir=tmp_path / "memory")
    memory.append_daily_note("今天完成了认证模块")
    notes = memory.get_recent_daily_notes(days=1)
    assert "认证模块" in notes[0]


def test_get_context(tmp_path):
    memory = LongTermMemory(memory_dir=tmp_path / "memory")
    memory.write_core("核心记忆")
    memory.append_daily_note("日志条目")
    context = memory.get_context()
    assert "核心记忆" in context
    assert "日志条目" in context
