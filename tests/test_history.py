from chatcc.memory.history import ConversationHistory


def test_add_and_get_messages(tmp_path):
    history = ConversationHistory(storage_dir=tmp_path)
    history.add_message("user", "你好")
    history.add_message("assistant", "你好！有什么可以帮你的？")
    messages = history.get_messages()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_message_count(tmp_path):
    history = ConversationHistory(storage_dir=tmp_path)
    for i in range(10):
        history.add_message("user", f"msg {i}")
    assert history.message_count == 10


def test_get_recent_messages(tmp_path):
    history = ConversationHistory(storage_dir=tmp_path)
    for i in range(20):
        history.add_message("user", f"msg {i}")
    recent = history.get_messages(limit=5)
    assert len(recent) == 5
    assert recent[-1]["content"] == "msg 19"


def test_persistence(tmp_path):
    h1 = ConversationHistory(storage_dir=tmp_path)
    h1.add_message("user", "persisted")
    h1.flush()

    h2 = ConversationHistory(storage_dir=tmp_path)
    messages = h2.get_messages()
    assert len(messages) == 1
    assert messages[0]["content"] == "persisted"


def test_truncate(tmp_path):
    history = ConversationHistory(storage_dir=tmp_path)
    for i in range(50):
        history.add_message("user", f"msg {i}")
    history.truncate(keep_recent=10)
    assert history.message_count == 10
