from __future__ import annotations

from collections import defaultdict
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

        Messages are grouped by project before summarizing so that each
        project's context remains coherent in long-term memory.

        Args:
            summarizer: Optional async callable(messages) -> str for generating summaries.
                       If None, uses a simple built-in summarizer.

        Returns:
            Combined summary text, or None if nothing to compress.
        """
        if not self.should_compress():
            return None

        removed = self._history.truncate(keep_recent=self.keep_recent)
        if not removed:
            return None

        groups = self._group_by_project(removed)
        summaries: list[str] = []

        for project, msgs in groups.items():
            if summarizer:
                try:
                    summary = await summarizer(msgs)
                except Exception:
                    logger.exception("Failed to generate summary with LLM")
                    summary = self._simple_summary(msgs)
            else:
                summary = self._simple_summary(msgs)

            label = f"[{project}]" if project else "[通用]"
            note = f"{label} 会话摘要 ({len(msgs)} 条消息): {summary}"
            self._longterm_memory.append_daily_note(note)
            summaries.append(note)

        combined = "\n".join(summaries)
        logger.info("Compressed {} messages into {} group(s)", len(removed), len(groups))
        return combined

    @staticmethod
    def _group_by_project(messages: list[dict]) -> dict[str | None, list[dict]]:
        groups: dict[str | None, list[dict]] = defaultdict(list)
        for msg in messages:
            groups[msg.get("project")].append(msg)
        return dict(groups)

    @staticmethod
    def _simple_summary(messages: list[dict]) -> str:
        """Simple built-in summarizer (no LLM)"""
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return f"压缩了 {len(messages)} 条历史消息"

        topics = []
        for msg in user_messages[:5]:
            content = msg.get("content", "")
            if len(content) > 50:
                content = content[:50] + "..."
            topics.append(content)

        topic_str = "; ".join(topics)
        return f"讨论话题: {topic_str} (共 {len(messages)} 条消息)"
