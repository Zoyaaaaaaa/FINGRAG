import json
import os
import re
import time
from typing import Any, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from langsmith import traceable

from src.config.settings import Settings
from src.memory.conversation_memory import ConversationMemory
from src.tools.neo4j_tools import Neo4jClient
from src.tools.qdrant_tools import QdrantStore
from src.rails import RailsOrchestrator


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
        self.rails_orchestrator = RailsOrchestrator(self.settings)
        
        # Rate limiting and retry configuration
        self.max_retries = 3
        self.base_delay = 2.0  # seconds
        self.max_delay = 30.0  # seconds
        self.llm_timeout = 60.0  # seconds
        self._last_llm_call = 0
        self._min_llm_interval = 1.0  # minimum seconds between LLM calls
        
        # Latency thresholds and fail-fast configuration
        self.neo4j_timeout = 5.0  # seconds
        self.qdrant_timeout = 15.0  # seconds
        self.max_total_latency = 180.0  # seconds for entire query
        self.query_start_time = 0
        
        self.graph = self._build_graph()
    
    def _wait_for_rate_limit(self):
        """Implement rate limiting between LLM calls."""
        current_time = time.time()
        time_since_last = current_time - self._last_llm_call
        
        if time_since_last < self._min_llm_interval:
            sleep_time = self._min_llm_interval - time_since_last
            time.sleep(sleep_time)
        
        self._last_llm_call = time.time()
    
    def _call_llm_with_retry(self, messages: list, timeout: float = 10.0) -> Any:
        """Call LLM with exponential backoff retry logic."""
        self._wait_for_rate_limit()
        
        for attempt in range(self.max_retries):
            try:
                # Set timeout for this attempt
                response = self.llm.invoke(messages, timeout=timeout)
                return response
                
            except Exception as exc:
                error_msg = str(exc).lower()
                
                # Check for rate limiting errors
                is_rate_limit = any(
                    keyword in error_msg 
                    for keyword in ["429", "rate limit", "quota", "resource_exhausted", "too_many_requests"]
                )
                
                # Check for timeout errors
                is_timeout = any(
                    keyword in error_msg 
                    for keyword in ["timeout", "timed out", "deadline"]
                )
                
                # If it's the last attempt, give up
                if attempt == self.max_retries - 1:
                    raise
                
                # Calculate exponential backoff delay
                if is_rate_limit:
                    # Longer delay for rate limiting
                    delay = min(self.base_delay * (2 ** attempt) + 5, self.max_delay)
                elif is_timeout:
                    # Moderate delay for timeouts
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay / 2)
                else:
                    # Standard delay for other errors
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay / 3)
                
                print(f"LLM call failed (attempt {attempt + 1}/{self.max_retries}), retrying in {delay:.1f}s: {exc}")
                time.sleep(delay)
        
        raise RuntimeError(f"LLM call failed after {self.max_retries} attempts")

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
        
        # RELATIONAL patterns (queries about relationships between entities - most specific check)
        # More comprehensive relationship keywords
        relational_keywords = [
            "relationship", "between", "connected to", "impact of", "collaboration between",
            "partnership", "partner with", "joint venture", "jv", "stake in", "technology transfer",
            "licensing", "platform licensing", "equity stake", "share of", "deal with", "agreement with"
        ]
        relational = any(word in lowered for word in relational_keywords)
        
        # FACTUAL patterns (queries seeking specific facts - but not if they sound like relationships)
        factual_keywords = ["what is", "which", "how much", "ticker", "code", "revenue", "stock", "market cap",
                            "what industry", "what sector", "industry is", "sector does",
                            "indian status", "country of origin", "report date", "deal status",
                            "presence level", "risk exposure", "industry group", "key player",
                            "stake percentage", "exchange", "status of", "source", "reported"]
        factual = any(word in lowered for word in factual_keywords)
        
        # SEMANTIC patterns (broad conceptual queries - more specific, avoid relationship keywords)
        semantic_keywords = [
            "tell me about", "analyze", "discuss", "explain", "describe",
            "what are the trends", "overview", "summary", "analysis of",
            "how does", "why", "compare", "versus", "vs", "industry",
            "market", "sector", "landscape", "ecosystem", "environment",
            "companies that", "which companies have", "list of",
            "all companies", "multiple companies", "various companies",
            "electric vehicle", "ev market", "battery industry", "automotive industry",
            "pharmaceutical", "healthcare", "manufacturing", "technology",
            "investment", "funding", "startup", "business environment",
            "overview of", "summary of", "description of", "explain the"
        ]
        semantic = any(word in lowered for word in semantic_keywords)
        
        # Improved intent classification logic (relational first, then factual, then semantic)
        if relational:
            intent = "RELATIONAL"
        elif factual and not relational:
            intent = "FACTUAL"
        elif semantic and not relational:
            intent = "SEMANTIC"
        else:
            # Default to SEMANTIC for unknown patterns
            intent = "SEMANTIC"
        
        # Query planning based on intent
        if intent == "RELATIONAL":
            plan = "HYBRID"
        elif intent == "FACTUAL":
            plan = "LOCAL"
        else:  # SEMANTIC
            plan = "GLOBAL"
        
        entities = re.findall(r"\b[A-Z][A-Za-z0-9&.-]{1,30}\b", query)
        return {"intent": {"intent": intent, "entities": entities, "domain": "financial"}, "plan": plan}

    @traceable(name="retrieve_financial_context", run_type="chain")
    def _retrieve(self, state: GraphState) -> dict[str, Any]:
        # Apply retrieval rails
        retrieval_decision = self.rails_orchestrator.execute_retrieval_rails_only(
            state["query"],
            state.get("intent", {}),
            state.get("plan", "GLOBAL"),
            state.get("top_k")
        )
        
        if not retrieval_decision.allowed:
            return {
                "graph_context": [],
                "vector_context": [],
                "sources": [],
                "retrieval_blocked": True,
                "retrieval_reason": retrieval_decision.reason
            }
        
        # Use the rail's max_results and filters
        max_results = retrieval_decision.max_results
        filters = retrieval_decision.filters or {}
        
        entities = state.get("intent", {}).get("entities", [])
        graph_context = self.neo4j.search(state["query"], entities, max_results) if state["plan"] in ("LOCAL", "HYBRID") else []
        vector_context = self.qdrant.search(state["query"], max_results) if state["plan"] in ("GLOBAL", "HYBRID") else []
        
        # Apply retrieval validation to results
        all_results = [{"type": "graph", "data": item} for item in graph_context]
        all_results.extend({"type": "vector", "data": item} for item in vector_context)
        
        filtered_results, validation_info = self.rails_orchestrator.retrieval_rails.validate_retrieval_results(
            all_results,
            retrieval_decision
        )
        
        # Separate back into graph and vector contexts
        graph_context = [item["data"] for item in filtered_results if item["type"] == "graph"]
        vector_context = [item["data"] for item in filtered_results if item["type"] == "vector"]
        sources = filtered_results
        
        # Fallback to vector-only if graph search fails or no results
        if not graph_context and not vector_context:
            vector_context = self.qdrant.search(state["query"], max_results)
            sources = [{"type": "vector", "data": item} for item in vector_context]
        
        return {
            "graph_context": graph_context,
            "vector_context": vector_context,
            "sources": sources,
            "retrieval_validation": validation_info
        }

    def _build_context(self, state: GraphState) -> dict[str, str]:
        blocks = [f"Conversation history:\n{self.memory.summary(state['session_id'])}"]
        blocks.extend(f"Graph: {json.dumps(item, default=str)}" for item in state.get("graph_context", []))
        blocks.extend(f"Document: {item['text']}" for item in state.get("vector_context", []))
        return {"context": "\n".join(blocks)[:8000]}

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
            response = self._call_llm_with_retry([HumanMessage(content=prompt)], timeout=self.llm_timeout)
        except Exception as exc:
            msg = str(exc)
            is_quota = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower() or "rate limit" in msg.lower()
            is_timeout = "504" in msg or "DEADLINE_EXCEEDED" in msg or "deadline" in msg.lower() or "timeout" in msg.lower() or "timed out" in msg.lower()
            if is_quota or is_timeout:
                retry = ""
                if "retry in" in msg.lower() or "retryDelay" in msg:
                    import re as _re
                    m = _re.search(r"retry in\s*([0-9.]+s)", msg, _re.I)
                    if m:
                        retry = f"Model `{self.settings.gemini_model}` is rate-limited. Automatic retry in {m.group(1)}."
                if is_timeout and not retry:
                    retry = f"LLM `{self.settings.gemini_model}` timed out (504) — showing extractive answer from graph + vector hits."
                fallback = self._fallback_answer(state, retry or f"LLM `{self.settings.gemini_model}` quota exhausted — showing extractive answer from graph + vector hits.")
                self.memory.add(state["session_id"], state["query"], fallback)
                return {"answer": fallback}
            raise
        answer = self._extract_text(response.content)
        self.memory.add(state["session_id"], state["query"], answer)
        return {"answer": answer}

    def query(self, query: str, session_id: str = "default", top_k: int = 8) -> dict[str, Any]:
        self.query_start_time = time.time()
        
        # Fail-fast check: if query too long, reject immediately
        if len(query) > 2000:
            return {
                "answer": "Query too long. Please limit your question to 2000 characters.",
                "plan": "REJECTED",
                "intent": {"intent": "REJECTED", "entities": [], "domain": "none"},
                "blocked": True,
                "guard_canonical": "query_too_long",
                "guard_flow": "reject",
                "guard_message": "Query too long",
                "guard_trace": {"decider": "length_check"},
                "sources": [],
                "graph_context": [],
                "vector_context": [],
                "context": "",
                "trace": {"step_0_guardrails": {"blocked": True, "reason": "Query too long"}},
                "session_id": session_id,
            }
        
        try:
            result = self.graph.invoke({"query": query, "session_id": session_id, "top_k": top_k})
        except Exception as e:
            # Check if this is a timeout or rate limit error
            error_msg = str(e).lower()
            elapsed = time.time() - self.query_start_time
            
            if elapsed > self.max_total_latency:
                # Query took too long, return fallback
                return {
                    "answer": f"Query processing timeout after {elapsed:.1f}s. Please try a simpler query or check your connection.",
                    "plan": "TIMEOUT",
                    "intent": {"intent": "TIMEOUT", "entities": [], "domain": "none"},
                    "blocked": False,
                    "sources": [],
                    "graph_context": [],
                    "vector_context": [],
                    "context": "",
                    "trace": {"error": f"Timeout after {elapsed:.1f}s"},
                    "session_id": session_id,
                }
            else:
                # Other error, re-raise
                raise
        
        # Check total latency and warn if excessive
        elapsed = time.time() - self.query_start_time
        if elapsed > self.max_total_latency:
            # Still return result but with warning
            result["latency_warning"] = f"Query took {elapsed:.1f}s, exceeding threshold of {self.max_total_latency}s"
        
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
            "step_5_latency": {
                "total_seconds": elapsed,
                "exceeded_threshold": elapsed > self.max_total_latency,
            }
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
        rails_orchestrator_ok = "ok" if hasattr(self, "rails_orchestrator") else "error"
        return {
            "gemini": "ok" if self.llm else "not_configured", 
            "qdrant": self.qdrant.health(), 
            "neo4j": self.neo4j.health(), 
            "guardrails": rails_ok, 
            "rails_orchestrator": rails_orchestrator_ok,
            "langsmith": "enabled" if self.settings.effective_langsmith_api_key else "not_configured"
        }

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
        
        # Add rails orchestrator status
        if hasattr(self, "rails_orchestrator"):
            base["rails_orchestrator_status"] = self.rails_orchestrator.get_rails_status()
        
        return base
