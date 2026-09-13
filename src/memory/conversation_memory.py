from collections import defaultdict, deque


class ConversationMemory:
    def __init__(self, window_size: int = 10):
        self._history = defaultdict(lambda: deque(maxlen=window_size))

    def add(self, session_id: str, query: str, answer: str) -> None:
        self._history[session_id].append({"query": query, "answer": answer})

    def get(self, session_id: str) -> list[dict[str, str]]:
        return list(self._history[session_id])

    def summary(self, session_id: str) -> str:
        entries = self.get(session_id)
        if not entries:
            return "No previous conversation."
        return "\n".join(f"User: {item['query']}\nAssistant: {item['answer'][:500]}" for item in entries)

    def clear(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._history.clear()
        else:
            self._history.pop(session_id, None)
