# FinGraphRAG System Architecture — Current Implementation (Sep 2026)

## Overview
FinGraphRAG is a hybrid RAG system for **Indian companies × Chinese partners**. It answers strictly from your CSV knowledge base (`src/data/stock_company.csv`, `src/data/stock_report.csv`, `src/data/Stock_industry_grouped_w_code.csv`) using:

* **Neo4j** — structured entity graph (`FinancialEntity` nodes, 316 records, `company_name`/`company_code`/`chinese_partner`/`relationship_type` etc.)
* **Qdrant** — dense vectors (`gemini-embedding-001`, 3072-d, cosine, collection `graphragfin` / `financial_documents`, 532 points)
* **Gemini** — LLM synthesis (`gemini-3-flash-preview` via `langchain-google-genai`, temperature 0.1) + topical guardrails
* **LangGraph** — stateful workflow engine; **LangSmith** tracing optional

If Neo4j or Qdrant are briefly unreachable (DNS/SSL hiccup, Aura pause), the app now self-heals and surfaces an honest error + hint instead of sticking in a broken state. If the LLM free-tier quota (429) is hit, an extractive fallback still returns the exact retrieved nodes/chunks.

---

## Live Architecture Flow

```
┌──────────────────────────────────────────────────────────────┐
│                     User Interface                           │
│              Streamlit  +  FastAPI (/health, /query)        │
└──────────────────────────────┬───────────────────────────────┘
                               │ QueryRequest { query, session_id, top_k }
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                FinGraphRAG Orchestrator                      │
│               LangGraph  (src/orchestrator.py)               │
│                                                              │
│  guard ──► understand ──► retrieve ──► build_context ──► synthesize │
│    │         (blocked? ─────► synthesize: canned refusal)    │
│    │  LangGraph conditional edge: guard.blocked ?            │
│    │     blocked → synthesize (no DB cost)                   │
│    │     continue → understand → retrieve → ... → synthesize │
└──────────────────────────────┬───────────────────────────────┘
                               ▼
 ┌─────────────────────┐  ┌──────────────────┐  ┌──────────────┐
 │ Nemo-style Guard    │  │ Query Understand │  │   Retrieval   │
 │ rails.co + Gemini   │  │  • Intent: REL/  │  │  Plan: HYB/   │
 │ classifier + scope  │  │    FACT/SEM      │  │  LOC/GLOB     │
 │ + canonical match   │  │  • Entities regex│  │               │
 └──────────┬──────────┘  └────────┬─────────┘  └──────┬────────┘
            └─────────────────────┼─────────────────────┘
                                  │ parallel (plan-gated)
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
           ┌──────────────────┐       ┌──────────────────┐
           │  Neo4j (graph)   │       │  Qdrant (vector) │
           │  Cypher: keys(n) │       │  embed_query +   │
           │  CONTAINS(term)  │       │  query_points    │
           │  + 1-hop neighbor│       │  score + metadata│
           └────────┬─────────┘       └────────┬─────────┘
                    └─────────────┬─────────────┘
                                  │ sources: [{type:graph|vector}]
                                  ▼
                    ┌──────────────────────────┐
                    │   Context Construction   │
                    │  memory.summary() +      │
                    │  Graph: json.dumps(node) │
                    │  Document: chunk.text    │
                    │  clipped to 20k chars    │
                    └────────────┬─────────────┘
                                 │ prompt: "Answer only from context..."
                                 ▼
                    ┌──────────────────────────┐
                    │   Gemini LLM (or        │
                    │   extractive fallback)   │
                    │  _synthesize → _extract_ │
                    │  text (handles block    │
                    │  signature) or          │
                    │  _fallback_answer on   │
                    │  429 → graph+chunk dump │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  Response                │
                    │  answer, plan, intent,  │
                    │  blocked, guard_trace,  │
                    │  sources, graph_context, │
                    │  vector_context, context,│
                    │  trace{0..4}, session_id │
                    └──────────────────────────┘
```

---

## Component Details

### 1. UI Layer
* **Streamlit `src/streamlit_app.py`** — wide layout, health sidebar, query input, `🛡️ Guardrails` step panel (whiteboard-style), `🛤️ How this answer was derived` (intent → Cypher → nodes/chunks → context), source expanders, conversation history, analytics tabs. Init: `FinGraphRAG(get_settings())` cached in `st.session_state.system`.
* **FastAPI `src/api.py`** — `GET /health` (degraded vs ok), `POST /query` → `QueryResponse`, `DELETE /memory/{session_id}`.
* **CLI `src/main.py`** — `serve` (uvicorn), `ingest <csv>`, `ask <query>`, `ui` (subprocess streamlit).
* Health sidebar now: filters to real services only (`gemini/qdrant/neo4j/guardrails/langsmith`), `🔄 Retry connections` button (`system.reconnect()` bypasses cooldown), Neo4j deep-dive (URI, configured→active DB, real error+hint), Qdrant deep-dive, `Rails: ... ✓`.

### 2. Guardrail Layer — Nemo-Style, Gemini-Only
* **Spec:** `src/guardrails_config/rails.co` (Colang 1.0) — `define user ask off topic` (10 utterances: joke, capital of france, poem, 2+2, dinner, game, movie, weather, election, sort python) | `define user ask financial question` (8 in-scope examples: Bharti–Haier, Reliance–CATL, Adani–BYD, Tata–Chery, SAIC stake, CATL partners, Consumer-Durables risk, Sany revenue) | `define bot refuse off topic` | `define flow handle off topic → stop` | `define flow handle financial question → execute financial_rag → stop`.
* **Nemo config:** `src/guardrails_config/config.yml` (`engine: google_genai`, `model: gemini-3-flash-preview`, `single_call.enabled: false`) — runnable verbatim under real NeMo on Python 3.10–3.13 (`NEMOGUARDRAILS_LLM_FRAMEWORK=langchain nemoguardrails chat --config src/guardrails_config`). Custom action `actions.py:financial_rag` delegates to the same `FinGraphRAG` pipeline.
* **Lightweight runtime `src/guardrails/fin_guardrails.py`** (ships with the app, required because NeMo doesn't install on Python 3.14): parses `rails.co`, builds `scope_terms` from your three CSVs, then per query:
  1. `LOAD rails.co` (counts)
  2. `SCOPE scan` (word-boundary hits among CSV terms + finance terms)
  3. **Canonical-example match** (difflib ≥0.85, deterministic — guarantees `tell me a joke` / `capital of france` always refuse without an LLM call, saving quota)
  4. otherwise **Gemini classifier** (`temperature:0`, JSON `{"canonical_form":...}`) — skips the noisy keyword hint, decides by meaning; on 429/any error falls back to scope-scan.
  5. `FLOW selection` + `BOT action` (`stop`, RAG skipped on off-topic). Full trace stored in `guard_trace.steps` and surfaced in Streamlit.

### 3. Orchestrator (LangGraph) `src/orchestrator.py`
* **State `GraphState`** — `query/session_id/top_k`, guard fields (`blocked/guard_canonical/guard_flow/guard_message/guard_trace`), `intent/plan`, `graph_context/vector_context/sources`, `context`, `answer`.
* **Nodes:**
  * `guard`: `FinGuardrails.check()` as above.
  * `understand` (static): `RELATIONAL` if `relationship|between|collaborate|partner|connected|impact`, else `FACTUAL` if `what is|which|how much|ticker|code|revenue`, else `SEMANTIC`; `plan = HYBRID|LOCAL|GLOBAL`; `entities = /\b[A-Z][A-Za-z0-9&.-]{1,30}\b/`.
  * `retrieve`: `neo4j.search(query, entities, top_k)` when `LOCAL|HYBRID`; `qdrant.search(query, top_k)` when `GLOBAL|HYBRID`; unified `sources`; fallback to vector-only when both empty. Neo4j Cypher matches **any string property** (`any(key in keys(n) where toLower(toString(n[key])) CONTAINS toLower(term))`) — fixes old `n.name/n.ticker` miss — and returns `labels, relationship, neighbor` (dataset has 0 explicit rels, so neighbors are `null` and Streamlit notes that).
  * `build_context`: `memory.summary() + Graph: json + Document: text`, truncated 20k.
  * `synthesize`: if `blocked` → canned refusal (0 LLM cost); else `ChatGoogleGenerativeAI(gemini-3-flash-preview).invoke()` → `_extract_text()` (handles Gemini block-with-signature list). **Fallback:** on `429/RESOURCE_EXHAUSTED` returns `_fallback_answer()` — deterministic extractive dump of up to 6 graph nodes + 6 chunks with sources — so the JSW×Chery query in your last turn no longer throws despite the quota banner. Memory is updated either way. `@traceable` for LangSmith.
* **`query()`** builds `trace{step_0_guardrails, step_1_understand, step_2_graph_retrieval{cypher/params/database/nodes_returned}, step_3_vector_retrieval{collection/chunks_returned}, step_4_context{chars}}` plus legacy `sources` for UI.
* **`health()` / `health_detail()` / `reconnect()`** — `gemini ok|not_configured`, `qdrant`, `neo4j`, `guardrails`, `langsmith`; detail adds `neo4j_detail{qdrant_detail}` with `hint`, `qdrant_collection`, `gemini_model`, `rails_path/exists`.

### 4. Data Storage

#### Neo4j `src/tools/neo4j_tools.py`
* `GraphDatabase.driver` against `NEO4J_URI` (`neo4j+s://5a76f90e.databases.neo4j.io`, instance `5a76f90e`). Handles Windows `CERTIFICATE_VERIFY_FAILED` by retrying `neo4j+ssc://`; **auto-discovers home DB** (`SHOW DATABASES` → home `5a76f90e`, else configured, else `None`) and prints `configured 'neo4j' unavailable, using '5a76f90e'`. `_ensure_driver()` with `RECONNECT_COOLDOWN_S=60` self-heals a transient `getaddrinfo failed` cold start on next `health()/search()`; `reconnect()` forces it from the sidebar; `search()` also injects stop-word-filtered fallback terms when regex finds no entities (e.g. lowercase query). `health_detail` adds DNS/SSL/auth hints.

#### Qdrant `src/tools/qdrant_tools.py`
* `QdrantClient(url, api_key, timeout=120)` + `GoogleGenerativeAIEmbeddings(gemini-embedding-001)`. `health()` → `get_collections()`; `health_detail()` with collections list + hints; `ensure_collection()`; `_embed_batch` with `35s*(attempt+1)` retry on 429 (5 attempts); `upsert` in batches of 5 (`time.sleep(2)` between); `search` → `embed_query` → `query_points(limit, with_payload=True)` → `{text,score,metadata}`.

### 5. AI/ML
* **Gemini LLM:** `gemini-3-flash-preview` (override via `GEMINI_MODEL` in `src/.env` / `.env`; alias `GEMINI_MODEL_NAME`). Default was `gemini-3.5-flash` which exhausts at 20 req/day on free tier — now visible as `429` fallback.
* **Embeddings:** `models/gemini-embedding-001` (configurable `EMBEDDING_DIMENSIONS=3072`).
* **Memory `src/memory/conversation_memory.py`:** in-process per-`session_id` window `MEMORY_WINDOW_SIZE=10` (Streamlit `streamlit_session`, FastAPI caller-chosen).

### 6. Config `src/config/settings.py`
* `BaseSettings` (Pydantic, `env_file=None`, `extra=ignore`), aliases `GOOGLE_API_KEY|GEMINI_API_KEY`, `GEMINI_MODEL|GEMINI_MODEL_NAME`, etc. Loads `project_root/.env` then `project_root/src/.env` (`override=False`). `@lru_cache get_settings()` — call `get_settings.cache_clear()` after editing `.env` without restart. Exposes `effective_langsmith_*`.

---

## Data Flows

### Ingestion `src/ingestion.py`
```
CSV (stock_company.csv / stock_report.csv / Stock_industry_grouped_w_code.csv)
  → pandas DataFrame → per-row  text = "field: value | field: value"
                           metadata = {source, row}
     ──► QdrantStore.upsert(documents)  [batch 5, embeddings, cosine 3072]
     └─► Neo4jClient.upsert_rows(rows)  [MERGE FinancialEntity {key}, SET += properties]
```

### Query (current, with guard + fallback)

```
User: "What is the relationship between JSW Group and Chery Automobile?"  (top_k=6)
  │
  ├─ 0. guard  FinGuardrails.check()
  │     LOAD rails.co (2 user forms, 2 bot msgs, 2 flows)
  │     SCOPE scan hits = ["chery","jsw","automobile"?]  (word-boundary)
  │     no canonical hit → Gemini classify → "ask financial question"
  │     → flow "handle financial question" → blocked=False
  │     trace.steps[5] recorded
  │
  ├─ 1. understand
  │     lowered contains "relationship between" → intent=RELATIONAL
  │     plan=HYBRID, entities=["What","JSW","Group","Chery","Automobile"]
  │
  ├─ 2. retrieve  (HYBRID → both)
  │     Neo4j  cypher= MATCH (n) WHERE any(key in keys(n) ...) CONTAINS toLower(term)
  │            params {entities:["What","JSW","Group","Chery","Automobile"], limit:6, database:"5a76f90e"}
  │            → 6 nodes e.g. JSW/Technology_Licensing/Chery_SAIC (stock_company.csv),
  │              plus Tata/Chery neighbors, etc. labels=["FinancialEntity"], relationship=null
  │     Qdrant collection=graphragfin → 6 chunks e.g. "company_code: JSW | ... chery ..."
  │     sources = 12 entries (type graph|vector)
  │
  ├─ 3. build_context
  │     "Conversation history:\nNo previous conversation.\nGraph: {...}\n...Document: ..."
  │     4245 chars (clipped 20000)
  │
  ├─ 4a. synthesize (happy path, quota available)
  │     invoke gemini-3-flash-preview with prompt "Answer only from context..."
  │     → _extract_text → "JSW Group and Chery Automobile have a Technology Licensing relationship.
  │       JSW signed a deal to source technology/components for its new-energy venture (DNA India,
  │       Confirmed 2025-08-20, stock_company.csv: Chery_SAIC)..."
  │     memory.add(session, query, answer)
  │
  └─ 4b. synthesize (quota exhausted — 429, as in your last turn)
        caught → _fallback_answer → deterministic extractive markdown:
        "**Answer from retrieved context (LLM synthesis skipped):** Q: What is the relationship..."
        "- Graph [stock_company.csv] relationship_type: Technology_Licensing | company_name: JSW Group | chinese_partner: Chery_SAIC ..."
        "- Chunk score=0.82 [stock_report.csv row 5]: company_name: JSW Group | chinese_partner: Chery Automobile | deal_type: Technology Licensing ..."
        Streamlit shows that answer + a warning "Model gemini-3-flash-preview is rate-limited. Automatic retry in 45s."
        but DOES NOT throw — path trace and sources stay intact.

Off-topic example:  "tell me a joke"
  guard canonical hit ("tell me a joke") → ask off topic → handle off topic → bot refuse off topic
  → blocked=True → synthesize returns REFUSAL_MESSAGE (0 graph/qdrant/LLM calls)
  → answer "I'm FinGraphRAG, a financial research assistant for Indian companies... I can't help with that..."
```

---

## Worked Example — What You Just Ran

**Input**
```json
{"query":"What is the relationship between JSW Group and Chery Automobile?","session_id":"streamlit_session","top_k":6}
```

**Step 0 — Guardrails**
```json
{"canonical_form":"ask financial question","flow":"handle financial question","blocked":false,
 "decider":"gemini","steps":[
  {"step":1,"name":"LOAD rails.co","detail":"2 user forms, 2 bot messages, 2 flows from .../guardrails_config/rails.co"},
  {"step":2,"name":"SCOPE scan (our CSV terms)","detail":"hits=['chery','jsw']"},
  {"step":3,"name":"GEMINI canonical-form classification","detail":"ask financial question — asks about partnership between two known companies"},
  {"step":4,"name":"FLOW selection","detail":"handle financial question"},
  {"step":5,"name":"BOT action","detail":"bot answer financial question → execute financial_rag → stop"}]}
```

**Step 1 — Understand**
```json
{"intent":"RELATIONAL","entities":["What","JSW","Group","Chery","Automobile"],"domain":"financial","plan":"HYBRID"}
```

**Step 2 — Retrieve**

Neo4j (Cypher actually executed, as shown in Streamlit Step 2):
```cypher
MATCH (n) WHERE any(key IN keys(n) WHERE n[key] IS NOT NULL AND any(term IN $entities WHERE toLower(toString(n[key])) CONTAINS toLower(term))) OPTIONAL MATCH (n)-[r]-(neighbor) RETURN properties(n) AS node, labels(n) AS labels, type(r) AS relationship, properties(neighbor) AS neighbor, labels(neighbor) AS neighbor_labels LIMIT $limit
-- params: {entities:["What","JSW","Group","Chery","Automobile"], limit:6, database:"5a76f90e"}
-- result 6 × {"node":{relationship_type:"Technology_Licensing",company_name:"JSW Group",chinese_partner:"Chery_SAIC",...},"labels":["FinancialEntity"],"relationship":null}
```

Qdrant:
```json
[{"text":"company_code: JSW | company_name: JSW Group | ... chinese_partner: Chery_SAIC | relationship_type: Technology_Licensing","score":0.84,"metadata":{"source":"stock_company.csv","row":3}},
 {"text":"company_name: JSW Group | chinese_partner: Chery Automobile | ... deal_type: Technology Licensing | ... source: DNA India","score":0.81,"metadata":{"source":"stock_report.csv","row":5}}]
```

**Step 3 — Context**
```
Conversation history:
No previous conversation.
Graph: {"node": {"relationship_type": "Technology_Licensing", "company_name": "JSW Group", ...}, "labels": ["FinancialEntity"], ...}
Document: company_code: JSW | company_name: JSW Group | ...
(4245 chars)
```

**Step 4 — Answer**

*With quota:* LLM synthesis above — **Technology Licensing — JSW sources technology/components from Chery Automobile for its new-energy/EV venture (DNA India, Confirmed 2025-08-20; stock_company.csv: Technology_Licensing, Chery_SAIC).**

*On 429 (your failing turn):* extractive fallback shown verbatim in ` Answer from retrieved context (LLM synthesis skipped)` with the exact graph nodes + chunk texts above.

---

## Key Features / Ops

* **Hybrid retrieval + honest provenance** — every answer exposes its intent/plan, exact Cypher+params, each graph node's full properties, each chunk's text+score+metadata, and merged context (Streamlit `🛤️ How this answer was derived`).
* **Topical safety** — off-topic never touches DB/LLM; on-topic meaning-based, not keyword-only (fixes `api∈capital`, `ev∈never` false positives).
* **Resilience** — Neo4j `+s → +ssc` fallback, DB auto-discovery, DNS reconnect (60s cooldown + manual `🔄 Retry`), Qdrant hints, LLM `_extract_text` + 429 fallback, streamlit 429 warning (not traceback).
* **Observability** — LangSmith `@traceable` on `retrieve`/`synthesize`, `GET /health` detail (real error+hint, rails path exists), `trace{0..4}` in `QueryResponse`.
* **Scalability** — Qdrant batch 5 + 2s gap + embedding retry `35s·attempt`, Neo4j connection pooling, context 20k limit, configurable `top_k`.

---

## Configuration

`src/.env` (actual, checked in with example keys — replace for prod) and `/.env` both loaded; `get_settings()` is `lru_cache`-ed.

| Key | Current | Notes |
|-----|---------|-------|
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | `AQ.Ab8RN...` | required; free-tier exhausted for `gemini-3.5-flash`, fresh quota for `gemini-3-flash-preview` |
| `GEMINI_MODEL` | `gemini-3-flash-preview` (default, alias `GEMINI_MODEL_NAME`) | was `gemini-3.5-flash`; switch in `.env` if quota hit |
| `EMBEDDING_MODEL` | `models/gemini-embedding-001` | 3072-d |
| `NEO4J_URI` | `neo4j+s://5a76f90e.databases.neo4j.io` | Aura free instance |
| `NEO4J_DATABASE` | `neo4j` (active resolved `5a76f90e`) | Aura's home DB is the instance id |
| `QDRANT_URL` / `QDRANT_COLLECTION` | `...cloud.qdrant.io` / `graphragfin` | also `financial_documents` exists |
| `LANGSMITH_*` | `FINGRAPHRAG` | tracing enabled |

---

## Run

```powershell
# Streamlit (currently on :8501, PID 8764 — refresh after .env/model change)
python -m streamlit run src/streamlit_app.py --server.headless true --server.port 8501
# or
python -m src.main ui

# FastAPI
python -m src.main serve --port 8000

# One-shot query (uses same LangGraph graph + fallback)
python -m src.main ask "What is the relationship between JSW Group and Chery Automobile?" --session-id demo

# NeMo server (needs Python 3.10–3.13 + pip install "nemoguardrails[google]")
NEMOGUARDRAILS_LLM_FRAMEWORK=langchain nemoguardrails chat --config src/guardrails_config
```

## Monitoring

* Sidebar `System Status` (Gemini/Qdrant/Neo4j/Guardrails/LangSmith), Neo4j+Qdrant detail expanders, retry button; `Qdrant collection ... · Model ...` + `Rails ... ✓` caption.
* Logs: `Neo4j: SSL verification failed ... using fallback ...`, `configured database 'neo4j' unavailable, using '5a76f90e'` are expected on first connect.

