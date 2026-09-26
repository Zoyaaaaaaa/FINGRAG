"""Multi-layer caching for FinGraphRAG — highlights platform features in UI.

Three layers (shown as badges in Streamlit):

1. Response Cache — exact query string → answer  (0ms, deterministic)
2. Semantic Cache — meaning match via Upstash Vector (or local fallback) threshold ≥0.88
3. Prompt Cache — hash(prompt+context) → LLM output reuse

Upstash Vector is preferred when UPSTASH_VECTOR_REST_URL/TOKEN are set
and `upstash-vector` is installed. Otherwise falls back to in-memory
brute-force (still demonstrates the concept without extra infra).

All layers are optional, observable and bypassed for off-topic blocked queries.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    query: str
    answer: str
    layer: str  # response | semantic | prompt
    score: float | None = None
    ts: float = field(default_factory=time.time)


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    response_hits: int = 0
    semantic_hits: int = 0
    prompt_hits: int = 0
    total_saved_ms: float = 0.0


class SemanticCacheStore:
    """Wraps Upstash Vector Index if available, else local list."""

    def __init__(self, url: str = "", token: str = "", threshold: float = 0.88):
        self.threshold = threshold
        self.url = url
        self.token = token
        self._upstash = None
        self._local: list[dict[str, Any]] = []
        self._embedder = None
        if url and token:
            try:
                from upstash_vector import Index  # type: ignore

                self._upstash = Index(url=url, token=token)
                # quick ping ( Upstash REST: info() )
                try:
                    self._upstash.info()
                except Exception:
                    pass
            except Exception:
                self._upstash = None
        # lazy embedder for local fallback
        self._local_vectors: list[list[float]] = []

    def _embed(self, text: str) -> list[float]:
        if self._embedder is None:
            try:
                from src.config.settings import get_settings

                s = get_settings()
                if s.google_api_key:
                    from langchain_google_genai import GoogleGenerativeAIEmbeddings

                    self._embedder = GoogleGenerativeAIEmbeddings(
                        model=s.embedding_model, google_api_key=s.google_api_key
                    )
            except Exception:
                self._embedder = None
        if self._embedder is not None:
            try:
                return self._embedder.embed_query(text)  # type: ignore
            except Exception:
                pass
        # fallback: hashed bag-of-words 384-dim
        import math

        vec = [0.0] * 384
        for tok in text.lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % 384] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        import math

        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    def upsert(self, qid: str, vector: list[float], metadata: dict[str, Any]):
        if self._upstash is not None:
            try:
                from upstash_vector import Vector  # type: ignore

                self._upstash.upsert(vectors=[Vector(id=qid, vector=vector, metadata=metadata)])
                return
            except Exception:
                pass
        # local
        self._local.append({"id": qid, "vector": vector, "metadata": metadata})

    def query(self, vector: list[float], top_k: int = 1, include_metadata: bool = True):
        if self._upstash is not None:
            try:
                res = self._upstash.query(vector=vector, top_k=top_k, include_metadata=include_metadata, include_vectors=False)
                # upstash_vector returns object with .scores / .vectors
                # normalize to list of {id, score, metadata}
                out = []
                for item in getattr(res, "result", res) or []:
                    # SDK shape varies; handle both
                    if isinstance(item, dict):
                        out.append(item)
                    else:
                        out.append(
                            {
                                "id": getattr(item, "id", ""),
                                "score": getattr(item, "score", 0),
                                "metadata": getattr(item, "metadata", {}),
                            }
                        )
                return out
            except Exception:
                pass
        # local brute force
        scored = []
        for entry in self._local:
            sc = self._cosine(vector, entry["vector"])
            scored.append({"id": entry["id"], "score": sc, "metadata": entry["metadata"]})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


class MultiLayerCache:
    """Response + Semantic + Prompt caches with stats and enhanced caching."""

    def __init__(self, settings: Any = None):
        s = settings
        url = getattr(s, "upstash_url", "") if s else ""
        tok = getattr(s, "upstash_token", "") if s else ""
        thresh = float(getattr(s, "cache_threshold", 0.88)) if s else 0.88
        self.semantic = SemanticCacheStore(url, tok, threshold=thresh)
        self._response: dict[str, CacheEntry] = {}
        self._prompt: dict[str, str] = {}
        self.stats = CacheStats()
        self._history: list[dict[str, Any]] = []
        
        # Enhanced cache configuration
        self.max_response_cache_size = 1000  # max entries in response cache
        self.max_history_size = 500  # max entries in history
        self.cache_warmup_queries = [
            "What is the relationship between JSW and Chery?",
            "Tell me about electric vehicle partnerships in India"
        ]  # queries to warm up cache with

    def _norm(self, q: str) -> str:
        return " ".join(q.strip().lower().split())

    def get_response(self, query: str) -> CacheEntry | None:
        key = self._norm(query)
        ent = self._response.get(key)
        if ent is not None:
            self.stats.hits += 1
            self.stats.response_hits += 1
            return ent
        return None

    def get_semantic(self, query: str) -> CacheEntry | None:
        vec = self.semantic._embed(query)
        hits = self.semantic.query(vec, top_k=1, include_metadata=True)
        if not hits:
            return None
        best = hits[0]
        score = float(best.get("score", 0) or 0)
        if score >= self.semantic.threshold:
            meta = best.get("metadata", {}) or {}
            ent = CacheEntry(query=meta.get("orig_query", query), answer=meta.get("answer", ""), layer="semantic", score=score)
            self.stats.hits += 1
            self.stats.semantic_hits += 1
            return ent
        return None

    def get_prompt(self, prompt_hash: str) -> str | None:
        ans = self._prompt.get(prompt_hash)
        if ans is not None:
            self.stats.hits += 1
            self.stats.prompt_hits += 1
            return ans
        return None

    def put_response(self, query: str, answer: str):
        key = self._norm(query)
        
        # Check cache size limit
        if len(self._response) >= self.max_response_cache_size:
            # Remove oldest entry (LRU eviction)
            oldest_key = min(self._response.keys(), key=lambda k: self._response[k].ts)
            del self._response[oldest_key]
        
        self._response[key] = CacheEntry(query=query, answer=answer, layer="response")
        
        # also upsert semantic
        try:
            vec = self.semantic._embed(query)
            qid = hashlib.sha256(self._norm(query).encode()).hexdigest()[:32]
            self.semantic.upsert(qid, vec, {"orig_query": query, "answer": answer})
        except Exception:
            pass
    
    def warmup_cache(self, query_func: callable):
        """Warm up cache with common queries."""
        print(f"Warming up cache with {len(self.cache_warmup_queries)} queries...")
        
        for query in self.cache_warmup_queries:
            try:
                # Check if already cached
                if self.get_response(query):
                    continue
                
                # Execute query to populate cache
                answer = query_func(query)
                self.put_response(query, answer)
                print(f"  Warmed: {query[:50]}...")
                
            except Exception as e:
                print(f"  Failed to warm: {query[:50]}... - {e}")
        
        print(f"Cache warmup complete. Response cache size: {len(self._response)}")
    
    def get_cache_stats(self) -> dict[str, Any]:
        """Get detailed cache statistics."""
        return {
            "response_cache_size": len(self._response),
            "response_cache_max": self.max_response_cache_size,
            "prompt_cache_size": len(self._prompt),
            "history_size": len(self._history),
            "history_max": self.max_history_size,
            "semantic_backend": "upstash" if self.semantic._upstash else "local",
            "overall_stats": {
                "hits": self.stats.hits,
                "misses": self.stats.misses,
                "response_hits": self.stats.response_hits,
                "semantic_hits": self.stats.semantic_hits,
                "prompt_hits": self.stats.prompt_hits,
                "total_saved_ms": self.stats.total_saved_ms,
                "hit_rate": self.hit_rate
            }
        }

    def put_prompt(self, prompt_hash: str, answer: str):
        self._prompt[prompt_hash] = answer

    def lookup(self, query: str) -> tuple[CacheEntry | None, str]:
        """Order: response (exact) -> semantic (meaning) -> miss."""
        ent = self.get_response(query)
        if ent:
            return ent, "response"
        ent = self.get_semantic(query)
        if ent:
            return ent, "semantic"
        self.stats.misses += 1
        return None, "miss"

    def record(self, query: str, layer: str, latency_ms: float, hit: bool):
        self._history.append(
            {"query": query[:80], "layer": layer, "hit": hit, "latency_ms": round(latency_ms, 1), "ts": time.strftime("%H:%M:%S")}
        )
        if len(self._history) > self.max_history_size:
            self._history = self._history[-self.max_history_size:]
        if hit:
            self.stats.total_saved_ms += max(0, latency_ms)

    @property
    def hit_rate(self) -> float:
        tot = self.stats.hits + self.stats.misses
        return self.stats.hits / tot if tot else 0.0

    def clear(self):
        self._response.clear()
        self._prompt.clear()
        # keep semantic local store but clear Upstash via delete? skip for safety
        self._history.clear()
        self.stats = CacheStats()
        print("Cache cleared successfully")
