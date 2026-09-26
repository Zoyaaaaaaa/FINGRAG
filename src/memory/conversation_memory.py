from collections import defaultdict, deque


class ConversationMemory:
    def __init__(self, window_size: int = 10):
        self._history = defaultdict(lambda: deque(maxlen=window_size))

    def add(self, session_id: str, query: str, answer: str) -> None:
        self._history[session_id].append({"query": query, "answer": answer})

    def get(self, session_id: str) -> list[dict[str, str]]:
        return list(self._history[session_id])

    def summary(self, session_id: str, max_turns: int = 3, max_chars: int = 800) -> str:
        """Last N turns only — keeps build_context fast (was 10×500 = 5k chars on every search)."""
        entries = self.get(session_id)[-max_turns:]
        if not entries:
            return "No previous conversation."
        return "\n".join(f"User: {item['query']}\nAssistant: {item['answer'][:max_chars]}" for item in entries)

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._history.clear()
        else:
            self._history.pop(session_id, None)
