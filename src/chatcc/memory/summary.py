from __future__ import annotations

from typing import Any

from chatcc.memory.history import ConversationHistory
from chatcc.memory.longterm import LongTermMemory

from loguru import logger


class SummaryManager:
    def __init__(
        self,
        history: ConversationHistory,
        longterm_memory: LongTermMemory,
        config: dict[str, Any] | None = None,
    ):
        self._history = history
        self._longterm_memory = longterm_memory
        cfg = config or {}
        self.threshold_messages: int = cfg.get("summarize_threshold", 50)
        self.keep_recent: int = cfg.get("keep_recent", 10)

    def should_compress(self) -> bool:
        """Check if conversation history exceeds compression threshold"""
        return self._history.message_count > self.threshold_messages

    async def compress(self, summarizer: Any = None) -> str | None:
        """Compress old messages: keep recent N, summarize old ones.

        Args:
            summarizer: Optional async callable(messages) -> str for generating summaries.
                       If None, uses a simple built-in summarizer.

        Returns:
            Summary text, or None if nothing to compress.
        """
        if not self.should_compress():
            return None

        # Truncate, getting removed messages
        removed = self._history.truncate(keep_recent=self.keep_recent)
        if not removed:
            return None

        # Generate summary
        if summarizer:
            try:
                summary = await summarizer(removed)
            except Exception:
                logger.exception("Failed to generate summary with LLM")
                summary = self._simple_summary(removed)
        else:
            summary = self._simple_summary(removed)

        # Store summary as daily note in long-term memory
        self._longterm_memory.append_daily_note(
            f"会话摘要 ({len(removed)} 条消息): {summary}"
        )

        logger.info("Compressed {} messages into summary", len(removed))
        return summary

    @staticmethod
    def _simple_summary(messages: list[dict]) -> str:
        """Simple built-in summarizer (no LLM)"""
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return f"压缩了 {len(messages)} 条历史消息"

        topics = []
        for msg in user_messages[:5]:  # First 5 user messages as topics
            content = msg.get("content", "")
            if len(content) > 50:
                content = content[:50] + "..."
            topics.append(content)

        topic_str = "; ".join(topics)
        return f"讨论话题: {topic_str} (共 {len(messages)} 条消息)"
