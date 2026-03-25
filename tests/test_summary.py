import pytest

from chatcc.memory.history import ConversationHistory
from chatcc.memory.longterm import LongTermMemory
from chatcc.memory.summary import SummaryManager


@pytest.fixture
def history(tmp_path):
    return ConversationHistory(storage_dir=tmp_path / "history")


@pytest.fixture
def longterm(tmp_path):
    return LongTermMemory(memory_dir=tmp_path / "memory")


@pytest.fixture
def summary_manager(history, longterm):
    return SummaryManager(
        history, longterm, config={"summarize_threshold": 5, "keep_recent": 2}
    )


def test_should_compress_false(summary_manager, history):
    for i in range(3):
        history.add_message("user", f"msg {i}")
    assert summary_manager.should_compress() is False


def test_should_compress_true(summary_manager, history):
    for i in range(6):
        history.add_message("user", f"msg {i}")
    assert summary_manager.should_compress() is True


async def test_compress(summary_manager, history, longterm):
    for i in range(6):
        history.add_message("user", f"话题 {i}")

    summary = await summary_manager.compress()
    assert summary is not None
    assert "话题" in summary
    assert history.message_count == 2  # keep_recent=2

    # Verify stored in longterm memory
    notes = longterm.get_recent_daily_notes(days=1)
    assert len(notes) > 0
    assert "会话摘要" in notes[0]


async def test_compress_not_needed(summary_manager, history):
    history.add_message("user", "hello")
    result = await summary_manager.compress()
    assert result is None


async def test_compress_with_custom_summarizer(summary_manager, history):
    for i in range(6):
        history.add_message("user", f"msg {i}")

    async def custom_summarizer(messages):
        return f"Custom summary of {len(messages)} messages"

    summary = await summary_manager.compress(summarizer=custom_summarizer)
    assert "Custom summary" in summary


async def test_compress_summarizer_error_fallback(summary_manager, history):
    for i in range(6):
        history.add_message("user", f"msg {i}")

    async def failing_summarizer(messages):
        raise RuntimeError("LLM error")

    summary = await summary_manager.compress(summarizer=failing_summarizer)
    assert summary is not None  # Falls back to simple summary
