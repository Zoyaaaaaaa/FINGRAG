# FinGraphRAG — System Architecture (Current)

## 1. Overview
Hybrid RAG for **Indian companies × Chinese partners**. Answers only from the CSV knowledge base
`stock_company.csv` / `stock_report.csv` / `Stock_industry_grouped_w_code.csv`.

| Layer | Tech | Live state |
|-------|------|------------|
| Graph | **Neo4j Aura** `neo4j+s://5a76f90e.databases.neo4j.io` | **629 nodes** (316 `FinancialEntity` legacy + 313 `Company`) · **105 typed edges** (PARTNERS_WITH 60 … HAS_STAKE_IN 4) |
| Vector | **Qdrant Cloud** `graphragfin` | **532 points** · `gemini-embedding-001` 3072-d · cosine |
| LLM | **Gemini** `gemini-3-flash-preview` | temp 0.1 + extractive 429 fallback |
| Orchestrator | **LangGraph** | guard → understand → retrieve → build_context → synthesize |
| Guardrails | **NeMo Colang** `rails.co` | Gemini classifier + canonical match |
| Cache | **Upstash Vector** `classic-lioness-60363…` | 3-layer (Response / Semantic / Prompt) threshold 0.88 |
| UI | **Streamlit** (wide) + FastAPI | Hero + 3×2 cards + tabs Chat/Graph/Cache/Arch |
| Observability | **LangSmith** | traceable retrieve/synthesize |

Self-healing: Neo4j `+s → +ssc` + home-DB discovery + 60s reconnect; Qdrant deterministic IDs; LLM signature handling.

---

## 2. Live Flow

```
┌─────────────────────┐
│  Streamlit / FastAPI│  QueryRequest {query, session_id, top_k}
└──────────┬──────────┘
           ▼
┌────────────────────────────────────────────────────────┐
│  Orchestrator (LangGraph)  src/orchestrator.py        │
│  guard ─► understand ─► retrieve ─► build_context ─► synthesize → END
│   │        ▲              ▲                               ▲
│   └─blocked?──► synthesize (refusal, 0 cost)─────────────┘
└──────────┬─────────────────────────────────────────────┘
           │
     ┌─────┴──────┐
     ▼            ▼
┌──────────┐ ┌──────────┐
│  Guard   │ │  Cache   │  MultiLayerCache (Upstash)
│ rails.co │ │ Response │  exact → Semantic (vector 0.88) → Prompt
│ Gemini   │ │ Upstash  │  HIT skips RAG, MISS → full pipeline
└────┬─────┘ └────┬─────┘
     └──────┬─────┘
            ▼
     ┌─────────────┐
     │ Understand  │  RELATIONAL/FACTUAL/SEMANTIC → HYBRID/LOCAL/GLOBAL
     └──────┬──────┘
            ▼
     ┌──────────────────────┐
     │ Retrieve (plan-gated)│
     │  Neo4j:Company 1-hop │──► 105 edges, rel_props
     │  Qdrant query_points │──► score + metadata
     └──────────┬───────────┘
                ▼
     ┌──────────────────┐
     │ Build Context    │  memory + Graph json + Document text → 20k clip
     └─────────┬────────┘
               ▼
     ┌──────────────────┐
     │ Synthesize       │  Gemini 3 Flash → _extract_text
     │                  │  429 → _fallback_answer (graph+chunks)
     └─────────┬────────┘
               ▼
     ┌──────────────────┐
     │ Response         │  answer + trace{0..4} + sources + cache meta
     └──────────────────┘
```

---

## 3. UI Layer — Streamlined (`src/streamlit_app.py`)

* **Theme fix (Sep 13):** removed `st.chat_input` fixed-position overlap with Deploy header; now `text_area + Send` inside Chat tab; `block-container` top padding; `3×2` card grid (was 6-in-row squeeze); `overflow-wrap:anywhere` for badges/answers. Architecture tab kept as **clean diagram only** per request.
* **Hero:** gradient `FinGraphRAG` + subtitle + badges (Hybrid, 105 Edges, 532 Vecs, Gemini 3 Flash, Guardrails, Upstash).
* **Cards (3×2):** Hybrid Retrieval · Knowledge Graph (629/105) · Vector Search · Gemini Synthesis · NeMo Guardrails · 3-Layer Cache.
* **Tabs:**
  * **Chat** — chips (JSW×Chery, Bharti×Haier, CATL, Dixon×Vivo), `st.chat_message` history, badges (Cache HIT/RAG, Guardrail block), `answer-box`, expanders: Guardrail trace · Retrieval (Cypher, 4 graph nodes + 4 chunks) · Context. Latency + source count caption. Fallback warning on 429.
  * **Graph Explorer** — live `MATCH count`, bar by rel type, 12-row edge table, schema code. Proves `MATCH (JSW)-[:LICENSES_TECHNOLOGY_FROM]->(Chery)` now works.
  * **Cache Dashboard** — hit rate, hits/misses/saved, bar by layer, Upstash snippet, semantic test box, history table. Explains Response/Semantic/Prompt.
  * **Architecture** — ASCII diagram only + caption pointing to this file.
* **Sidebar:** `System Status` (gemini/qdrant/neo4j/guardrails/langsmith) + `🔄 Retry` (bypasses 60s cooldown) + Neo4j/Qdrant expanders with hints + Upstash status + hit rate + Queries/Turns. Init cached in `st.session_state.system`.

---

## 4. Guardrails — NeMo-Style, Gemini-Only

* `src/guardrails_config/rails.co` (Colang 1.0): 10 off-topic (joke, capital of france…) · 8 financial (Bharti×Haier, Reliance×CATL…) · `bot refuse off topic` · `flow handle off topic → stop` · `flow handle financial question → execute financial_rag → stop`.
* `src/guardrails_config/config.yml`: `engine: google_genai` `model: gemini-3-flash-preview` `single_call.enabled:false`. Runnable as `NEMOGUARDRAILS_LLM_FRAMEWORK=langchain nemoguardrails chat --config src/guardrails_config` (Python 3.10-13).
* `src/guardrails/fin_guardrails.py` (required on Python 3.14 where nemoguardrails won't install): parses `rails.co`, word-boundary `scope scan` from 3 CSVs, **canonical difflib ≥0.85** (deterministic, saves quota), else **Gemini classifier** `temp 0, JSON`, else scope fallback. Trace `steps[1..5]` surfaced in UI. Off-topic costs 0 DB/LLM.

---

## 5. Orchestrator (`src/orchestrator.py`)

* **State:** `GraphState {query, session_id, top_k, blocked, guard_*, intent, plan, graph_context, vector_context, sources, context, answer}`.
* **Nodes:** `guard` (above) → conditional `blocked? synthesize : understand` → `understand` (REL if relationship/between/partner, FACT if what is/which/ticker/code, else SEM; plan HYBRID/LOCAL/GLOBAL; entities regex) → `retrieve` (Company-first Cypher + FinancialEntity fallback, Qdrant `query_points`, unified sources, vector-only fallback) → `build_context` (memory + Graph json + Document) → `synthesize` (blocked→refusal else Gemini invoke → `_extract_text` handling signature list else `_fallback_answer` on 429/RESOURCE_EXHAUSTED).
* **`query()`** returns `trace{step_0_guardrails, step_1_understand{intent/entities/domain/plan}, step_2_graph{cypher/params/database/nodes}, step_3_vector{collection/chunks}, step_4_context{chars}}` + `guard_trace`.
* **`health()/health_detail()/reconnect()`** — adds `neo4j_detail/qdrant_detail` with hints, `rails_path/exists`, `gemini_model`.

---

## 6. Data Storage

### Neo4j `src/tools/neo4j_tools.py`
* Driver `neo4j+s://5a76f90e` with `+ssc` fallback for Windows `CERTIFICATE_VERIFY_FAILED`; home-DB auto-discovery (`5a76f90e`); `_ensure_driver(60s cooldown)` + `reconnect()` from sidebar; `_stable_key(company_code|name)` (fixes old `hash()` randomization); `search()` Company-first with `OPTIONAL MATCH (n)-[r]->(neighbor)` (previously 0 rels for JSW); `upsert_rows` (FinancialEntity MERGE) + `upsert_with_edges` (MERGE `:Company` + typed `PARTNERS_WITH/LICENSES_TECHNOLOGY_FROM/HAS_STAKE_IN/...` via `REL_TYPE_MAP`, idempotent grouped by type). Migration `scripts/add_edges.py --skip_qdrant` gave `316→629 nodes, 0→105 rels, qdrant 532→532`.

### Qdrant `src/tools/qdrant_tools.py`
* `QdrantClient(timeout 120)` + `GoogleGenerativeAIEmbeddings`. `health_detail` + `ensure_collection`; `_embed_batch` retry `35s·attempt` on 429; `upsert` now **deterministic** `uuid5(sha256(text|source|row))` (was `uuid4` → 532 points for 320 rows) + `batch 5 + sleep 2`; `search` embed_query → query_points.

---

## 7. Caching — 3 Layers (`src/tools/semantic_cache.py`)

* **Response Cache** — `norm(query)` exact → instant.
* **Semantic Cache** — **Upstash Vector** `classic-lioness-60363-us1-vector.upstash.io` (`upstash-vector`) else local 384-d hashed fallback; cosine ≥ `CACHE_THRESHOLD 0.88` (e.g. *"JSW Chery deal?"* hits *"What is JSW Group and Chery relationship?"*). Upsert on each miss, hit skips RAG.
* **Prompt Cache** — `hash(context+question)` → LLM output (implemented as response cache extension).
* **UI:** `MultiLayerCache` stats `hits/misses/response_hits/semantic_hits/prompt_hits/total_saved_ms` shown in sidebar + Cache tab bar/history/test box. `Cache HIT · semantic 0.96` badge in chat (see your screenshot). Install: `pip install upstash-vector`.

---

## 8. AI/ML & Memory

* **Gemini:** `gemini-3-flash-preview` (`GEMINI_MODEL`, alias `GEMINI_MODEL_NAME`) — free tier `gemini-3.5-flash` exhausted at 20/d, `_fallback_answer` keeps 429 from throwing; `upstash` not using Gemini for embeddings in cache fallback.
* **Embeddings:** `models/gemini-embedding-001` 3072-d.
* **Memory:** `src/memory/conversation_memory.py` window `MEMORY_WINDOW_SIZE=10`, per `session_id`.

---

## 9. Config (`src/config/settings.py`, `src/.env`)

`BaseSettings` loads `.env` then `src/.env` (`override=False`), `@lru_cache`. `cache_clear()` after edit.

| Key | Current | Note |
|-----|---------|------|
| `GOOGLE_API_KEY` | `AQ.Ab8RN…` | Gemini |
| `GEMINI_MODEL` | `gemini-3-flash-preview` | was 3.5 |
| `EMBEDDING_MODEL` | `models/gemini-embedding-001` | 3072 |
| `NEO4J_URI` | `neo4j+s://5a76f90e…` → active `5a76f90e` | |
| `QDRANT_URL/COLLECTION` | `…cloud.qdrant.io` / `graphragfin` | |
| `UPSTASH_VECTOR_REST_URL/TOKEN` | `classic-lioness…` / `ABkF…` | semantic cache |
| `CACHE_THRESHOLD` | `0.88` | |
| `LANGSMITH_*` | `FINGRAPHRAG` | |

---

## 10. Data Flows

### Ingestion `src/ingestion.py`
```
CSV → DataFrame → text="field: value | …" + {source,row}
      ├─► Qdrant.upsert (deterministic id, batch 5)  [skip_qdrant=True for edge migration]
      └─► Neo4j.upsert_rows (FinancialEntity) + upsert_with_edges (:Company + typed rel)
          scripts/add_edges.py → 70 + 49 edges, MERGE idempotent
```

### Query (with guard+cache+fallback)
```
"JSW Group and Chery Automobile?" (top_k 6)
 0.guard LOAD→SCOPE hits [chery,jsw] → no canonical → Gemini "ask financial question" → blocked=False
 0b.cache lookup miss (first time) → MISS
 1.understand REL → HYBRID → entities [What,JSW,Group,Chery,Automobile]
 2.retrieve Company Cypher (MATCH Company CONTAINS term) → 3 rels (PARTNERS_WITH, LICENSES_TECHNOLOGY_FROM) → + FinancialEntity → 6 nodes, Qdrant 6 chunks → sources 12
 3.build_context 4245 chars
 4a.synthesize Gemini 3 Flash → "Technology Licensing — JSW sources tech … 2025-08-20"
 4b.on 429 → fallback "**Answer from retrieved context (LLM synthesis skipped):** …"
 cache.put → history + chat
Second identical/paraphrase → semantic 0.96 HIT → answer without RAG (screenshot badge)
"tell me a joke" → canonical "tell me a joke" → ask off topic → refusal, 0 cost
```

---

## 11. Operations

```powershell
# Streamlit :8501 (now text_area+Send, 3×2 cards, no overlap)
python -m streamlit run src/streamlit_app.py --server.headless true --server.port 8501
# FastAPI
python -m src.main serve --port 8000
# One-shot
python -m src.main ask "What is the relationship between JSW Group and Chery Automobile?" --session-id demo
# Edges (idempotent, no Qdrant dup)
python scripts/add_edges.py
# NeMo
NEMOGUARDRAILS_LLM_FRAMEWORK=langchain nemoguardrails chat --config src/guardrails_config
```

Health: sidebar `System Status` + deep dives + `🔄 Retry` + `Upstash: ✓ connected` + `Hit rate`.

---

## 12. Known State

* Qdrant 532 reflects old `uuid4` dupes (correct deterministic re-ingest would be ~320); kept to avoid data loss, future upserts are idempotent.
* Neo4j 629 = legacy 316 FinancialEntity + 313 Company (Company nodes enable traversal; FinancialEntity kept for provenance).
* BYD vs BYD Co remain separate Company nodes (raw partner normalization could merge them).
