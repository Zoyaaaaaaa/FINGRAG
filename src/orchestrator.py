import json
import os
import re
from typing import Any, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from langsmith import traceable

from src.config.settings import Settings
from src.memory.conversation_memory import ConversationMemory
from src.tools.neo4j_tools import Neo4jClient
from src.tools.qdrant_tools import QdrantStore


class GraphState(TypedDict, total=False):
    query: str
    session_id: str
    top_k: int
    # NeMo-style guardrail gate (rails.co, Gemini decider) — runs before anything else
    blocked: bool
    guard_canonical: str
    guard_flow: str
    guard_message: str
    guard_trace: dict[str, Any]
    intent: dict[str, Any]
    plan: str
    graph_context: list[dict[str, Any]]
    vector_context: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    context: str
    answer: str


class FinGraphRAG:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        api_key = self.settings.effective_langsmith_api_key
        if api_key:
            os.environ.setdefault("LANGCHAIN_API_KEY", api_key)
            os.environ.setdefault("LANGSMITH_API_KEY", api_key)
            os.environ.setdefault("LANGCHAIN_TRACING_V2", str(self.settings.effective_langsmith_tracing).lower())
            os.environ.setdefault("LANGSMITH_TRACING", str(self.settings.effective_langsmith_tracing).lower())
            os.environ.setdefault("LANGCHAIN_PROJECT", self.settings.effective_langsmith_project)
            os.environ.setdefault("LANGSMITH_PROJECT", self.settings.effective_langsmith_project)
            os.environ.setdefault("LANGSMITH_ENDPOINT", self.settings.langsmith_endpoint)
        self.memory = ConversationMemory(self.settings.memory_window_size)
        self.neo4j = Neo4jClient(self.settings)
        self.qdrant = QdrantStore(self.settings)
        self.llm = ChatGoogleGenerativeAI(model=self.settings.gemini_model, google_api_key=self.settings.google_api_key, temperature=0.1) if self.settings.google_api_key else None
        from src.guardrails.fin_guardrails import FinGuardrails
        self.guards = FinGuardrails(self.settings)
        self.graph = self._build_graph()

    def _guard(self, state: GraphState) -> dict[str, Any]:
        """Step 0 — Colang topical gate. Off-topic stops here, RAG never runs."""
        decision = self.guards.check(state["query"])
        return {
            "blocked": decision.blocked,
            "guard_canonical": decision.canonical_form,
            "guard_flow": decision.flow,
            "guard_message": decision.bot_message or "",
            "guard_trace": decision.trace,
        }

    def _build_graph(self):
        workflow = StateGraph(GraphState)
        workflow.add_node("guard", self._guard)
        workflow.add_node("understand", self._understand)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("build_context", self._build_context)
        workflow.add_node("synthesize", self._synthesize)
        workflow.set_entry_point("guard")
        # Off-topic: guard -> synthesize (refusal, no retrieval). On-topic: full RAG path.
        workflow.add_conditional_edges(
            "guard",
            lambda s: "blocked" if s.get("blocked") else "continue",
            {"blocked": "synthesize", "continue": "understand"},
        )
        workflow.add_edge("understand", "retrieve")
        workflow.add_edge("retrieve", "build_context")
        workflow.add_edge("build_context", "synthesize")
        workflow.add_edge("synthesize", END)
        return workflow.compile()

    @staticmethod
    def _understand(state: GraphState) -> dict[str, Any]:
        query = state["query"]
        lowered = query.lower()
        relational = any(word in lowered for word in ("relationship", "between", "collaborate", "partner", "connected", "impact"))
        factual = any(word in lowered for word in ("what is", "which", "how much", "ticker", "code", "revenue"))
        intent = "RELATIONAL" if relational else "FACTUAL" if factual else "SEMANTIC"
        plan = "HYBRID" if relational else "LOCAL" if factual else "GLOBAL"
        entities = re.findall(r"\b[A-Z][A-Za-z0-9&.-]{1,30}\b", query)
        return {"intent": {"intent": intent, "entities": entities, "domain": "financial"}, "plan": plan}

    @traceable(name="retrieve_financial_context", run_type="chain")
    def _retrieve(self, state: GraphState) -> dict[str, Any]:
        entities = state.get("intent", {}).get("entities", [])
        graph_context = self.neo4j.search(state["query"], entities, state.get("top_k", 8)) if state["plan"] in ("LOCAL", "HYBRID") else []
        vector_context = self.qdrant.search(state["query"], state.get("top_k", 8)) if state["plan"] in ("GLOBAL", "HYBRID") else []
        sources = [{"type": "graph", "data": item} for item in graph_context]
        sources.extend({"type": "vector", "data": item} for item in vector_context)
        # Fallback to vector-only if graph search fails or no results
        if not graph_context and not vector_context:
            vector_context = self.qdrant.search(state["query"], state.get("top_k", 8))
            sources.extend({"type": "vector", "data": item} for item in vector_context)
        return {"graph_context": graph_context, "vector_context": vector_context, "sources": sources}

    def _build_context(self, state: GraphState) -> dict[str, str]:
        blocks = [f"Conversation history:\n{self.memory.summary(state['session_id'])}"]
        blocks.extend(f"Graph: {json.dumps(item, default=str)}" for item in state.get("graph_context", []))
        blocks.extend(f"Document: {item['text']}" for item in state.get("vector_context", []))
        return {"context": "\n".join(blocks)[:20000]}

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Gemini may return str OR list of content blocks with signatures — extract readable text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    # e.g. {"type": "text", "text": "...", "extras": {"signature": ...}}
                    if "text" in block and isinstance(block["text"], str):
                        parts.append(block["text"])
                    elif "content" in block:
                        parts.append(FinGraphRAG._extract_text(block["content"]))
                elif hasattr(block, "text"):
                    try:
                        parts.append(str(block.text))
                    except Exception:
                        pass
                elif hasattr(block, "content"):
                    parts.append(FinGraphRAG._extract_text(block.content))
            text = "\n".join(p for p in parts if p).strip()
            return text if text else str(content)
        return str(content)

    def _fallback_answer(self, state: GraphState, reason: str = "") -> str:
        """Deterministic extractive answer from already-retrieved graph+vector blocks.

        Used when the LLM is quota-exhausted (429) so the user still gets an
        answer with exact sources and the path trace stays intact.
        """
        lines: list[str] = []
        if reason:
            lines.append(f"> Note: {reason}")
            lines.append("")
        # Pull the top facts directly — no LLM call at all.
        for item in (state.get("graph_context") or [])[:6]:
            node = item.get("node") or {}
            # Prefer a human summary rather than raw dump
            if "deal_details" in node:
                lines.append(f"- Graph [{node.get('source','')}] **{node.get('company_name','')}** — {node['deal_details']} (status: {node.get('status','')}, {node.get('report_date','')})")
            else:
                kv = " | ".join(f"{k}: {v}" for k, v in node.items() if k not in ("key",) and v)
                lines.append(f"- Graph [{node.get('source','')}] {kv}")
        for item in (state.get("vector_context") or [])[:6]:
            txt = item.get("text", "").strip()
            meta = item.get("metadata", {}) or {}
            if txt:
                lines.append(f"- Chunk score={item.get('score',0):.3f} [{meta.get('source','')} row {meta.get('row','')}]: {txt}")
        if not lines:
            lines.append("No graph or vector context was retrieved for this query.")
        header = f"**Answer from retrieved context (LLM synthesis skipped):**\n\nQ: {state.get('query','')}\n"
        return header + "\n".join(lines)

    @traceable(name="synthesize_financial_answer", run_type="llm")
    def _synthesize(self, state: GraphState) -> dict[str, str]:
        if state.get("blocked"):
            # Colang `handle off topic` flow: canned refusal, no LLM / DB cost.
            answer = state.get("guard_message", "")
            self.memory.add(state["session_id"], state["query"], answer)
            return {"answer": answer}
        if not self.llm:
            raise RuntimeError("GOOGLE_API_KEY is not configured")
        prompt = f"""You are a careful financial research assistant. Answer only from the context below.
If the context is insufficient, say so clearly. Include concise source references where available.
Question: {state['query']}
Context:
{state.get('context', '')}
"""
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
        except Exception as exc:  # noqa: BLE001 — quota / network resilience
            msg = str(exc)
            is_quota = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()
            if is_quota:
                retry = ""
                if "retry in" in msg.lower() or "retryDelay" in msg:
                    import re as _re
                    m = _re.search(r"retry in\s*([0-9.]+s)", msg, _re.I)
                    if m:
                        retry = f"Model `{self.settings.gemini_model}` is rate-limited. Automatic retry in {m.group(1)}."
                fallback = self._fallback_answer(state, retry or f"LLM `{self.settings.gemini_model}` quota exhausted — showing extractive answer from graph + vector hits.")
                self.memory.add(state["session_id"], state["query"], fallback)
                return {"answer": fallback}
            raise
        answer = self._extract_text(response.content)
        self.memory.add(state["session_id"], state["query"], answer)
        return {"answer": answer}

    def query(self, query: str, session_id: str = "default", top_k: int = 8) -> dict[str, Any]:
        result = self.graph.invoke({"query": query, "session_id": session_id, "top_k": top_k})
        graph_context = result.get("graph_context", [])
        vector_context = result.get("vector_context", [])
        # Full provenance trace: exactly how the agent derived the answer
        trace = {
            "step_0_guardrails": {
                "canonical_form": result.get("guard_canonical"),
                "flow": result.get("guard_flow"),
                "blocked": result.get("blocked", False),
                "decider": (result.get("guard_trace") or {}).get("decider"),
                "steps": (result.get("guard_trace") or {}).get("steps", []),
            },
            "step_1_understand": {
                "intent": result.get("intent", {}).get("intent"),
                "entities": result.get("intent", {}).get("entities", []),
                "domain": result.get("intent", {}).get("domain"),
                "plan": result.get("plan"),
                "explanation": (
                    f"Intent={result.get('intent', {}).get('intent')} → "
                    f"Plan={result.get('plan')} (HYBRID=graph+vector, LOCAL=graph only, GLOBAL=vector only)"
                ),
            },
            "step_2_graph_retrieval": {
                "ran": result.get("plan") in ("LOCAL", "HYBRID"),
                "cypher": getattr(self.neo4j, "last_cypher", None),
                "params": getattr(self.neo4j, "last_params", None),
                "database": getattr(self.neo4j, "active_database", None),
                "nodes_returned": len(graph_context),
            },
            "step_3_vector_retrieval": {
                "ran": result.get("plan") in ("GLOBAL", "HYBRID") or not graph_context,
                "collection": self.qdrant.settings.qdrant_collection,
                "chunks_returned": len(vector_context),
            },
            "step_4_context": {
                "chars": len(result.get("context", "")),
            },
        }
        guard_trace = result.get("guard_trace") or {}
        return {
            "answer": result["answer"],
            "plan": result.get("plan", ""),
            "intent": result.get("intent", {}),
            "blocked": result.get("blocked", False),
            "guard_canonical": result.get("guard_canonical"),
            "guard_flow": result.get("guard_flow"),
            "guard_trace": guard_trace,
            "sources": result.get("sources", []),
            "graph_context": graph_context,
            "vector_context": vector_context,
            "context": result.get("context", ""),
            "trace": trace,
            "session_id": session_id,
        }

    def health(self) -> dict[str, str]:
        rails_ok = "ok" if hasattr(self, "guards") and self.guards.rails.get("flows") else "error"
        return {"gemini": "ok" if self.llm else "not_configured", "qdrant": self.qdrant.health(), "neo4j": self.neo4j.health(), "guardrails": rails_ok, "langsmith": "enabled" if self.settings.effective_langsmith_api_key else "not_configured"}

    def reconnect(self) -> dict[str, Any]:
        """Force-retry all DB connections (sidebar button). Bypasses cooldowns."""
        self.neo4j.reconnect()
        return self.health_detail()

    def health_detail(self) -> dict[str, Any]:
        base = self.health()
        base["neo4j_detail"] = self.neo4j.health_detail() if hasattr(self.neo4j, "health_detail") else {}
        base["qdrant_detail"] = self.qdrant.health_detail() if hasattr(self.qdrant, "health_detail") else {}
        base["qdrant_collection"] = self.qdrant.settings.qdrant_collection
        base["gemini_model"] = self.settings.gemini_model
        rails_path = getattr(getattr(self, "guards", None), "rails", {}).get("path", "")
        base["rails_path"] = rails_path
        try:
            from pathlib import Path as _Path
            base["rails_exists"] = bool(rails_path) and _Path(str(rails_path)).exists()
        except Exception:
            base["rails_exists"] = False
        return base
