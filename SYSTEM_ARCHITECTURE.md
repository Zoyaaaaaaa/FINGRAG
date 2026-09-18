# FinGraphRAG — Complete System Architecture

## 1. Overview
Hybrid RAG for **Indian companies × Chinese partners** with comprehensive guardrails protection. Answers only from the CSV knowledge base `stock_company.csv` / `stock_report.csv` / `Stock_industry_grouped_w_code.csv`.

|| Layer | Tech | Live state |
||-------|------|------------|
|| **API Gateway** | **FastAPI** + Streamlit | Query routing, initial validation |
|| **Content Guardrails** | **NeMo Colang** `rails.co` | Topic filtering, intent classification |
|| **Technical Rails** | **Custom Python** `src/rails/` | Input/Retrieval/Execution/Output safety |
|| **Orchestrator** | **LangGraph** | guard → understand → retrieve → build_context → synthesize |
|| **Graph** | **Neo4j Aura** `neo4j+s://5a76f90e.databases.neo4j.io` | **629 nodes** (316 `FinancialEntity` legacy + 313 `Company`) · **105 typed edges** (PARTNERS_WITH 60 … HAS_STAKE_IN 4) |
|| **Vector** | **Qdrant Cloud** `graphragfin` | **532 points** · `gemini-embedding-001` 3072-d · cosine |
|| **LLM** | **Gemini** `gemini-3-flash-preview` | temp 0.1 + extractive 429 fallback |
|| **Cache** | **Upstash Vector** `classic-lioness-60363…` | 3-layer (Response / Semantic / Prompt) threshold 0.88 |
|| **UI** | **Streamlit** (wide) + FastAPI | Hero + 3×2 cards + tabs Chat/Graph/Cache/Arch |
|| **Observability** | **LangSmith** | traceable retrieve/synthesize |

**Dual-Layer Protection:**
- **Content Guardrails**: Business logic (what questions to answer)
- **Technical Rails**: Security safety (how to safely process operations)

Self-healing: Neo4j `+s → +ssc` + home-DB discovery + 60s reconnect; Qdrant deterministic IDs; LLM signature handling.

---

## 2. Complete System Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER QUERY                                         │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      API GATEWAY (FastAPI/Streamlit)                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  INPUT RAILS (First Line of Defense)                                   │  │
│  │  • Query length validation (min/max limits)                            │  │
│  │  • Injection pattern detection (SQL, XSS, script)                      │  │
│  │  • Character safety checks                                              │  │
│  │  • Query sanitization (whitespace, control chars)                      │  │
│  │  • Query structure analysis                                            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   CONTENT GUARDRAILS (rails.co)                               │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  NeMo-Style Topic Filtering                                             │  │
│  │  • Topic classification (financial vs off-topic)                       │  │
│  │  • Intent detection (RELATIONAL/FACTUAL/SEMANTIC)                       │  │
│  │  • Domain scope (Indian companies × Chinese partners)                   │  │
│  │  • Canonical form matching (deterministic ≥0.85 similarity)            │  │
│  │  • Gemini classifier fallback (temp=0, JSON)                           │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  Decision: blocked? → Refusal (0 cost) │ allowed? → Continue                 │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   MULTI-LAYER CACHE (Upstash Vector)                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Layer 1: Response Cache (exact match)                                 │  │
│  │  Layer 2: Semantic Cache (cosine ≥0.88)                                 │  │
│  │  Layer 3: Prompt Cache (context hash)                                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  HIT → Return cached answer (skip RAG) │ MISS → Continue to RAG pipeline  │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              ORCHESTRATOR (LangGraph State Machine)                          │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Node: UNDERSTAND                                                      │  │
│  │  • Intent classification (RELATIONAL/FACTUAL/SEMANTIC)                 │  │
│  │  • Entity extraction (capitalized words, company names)                │  │
│  │  • Query planning (HYBRID/LOCAL/GLOBAL)                               │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                   │                                         │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Node: RETRIEVE (with RETRIEVAL RAILS)                                │  │
│  │  • RETRIEVAL RAILS:                                                   │  │
│  │    - Sensitive data detection (PII, personal information)              │  │
│  │    - Query complexity analysis and limiting                            │  │
│  │    - Scope control (full/limited/none access)                         │  │
│  │    - Dynamic max-results adjustment                                   │  │
│  │  • Neo4j: Company-first Cypher + 1-hop relationships                   │  │
│  │  • Qdrant: Vector similarity search (gemini-embedding-001)            │  │
│  │  • Result validation and quality filtering                             │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                   │                                         │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Node: BUILD CONTEXT                                                  │  │
│  │  • Conversation memory (10-turn window)                               │  │
│  │  • Graph context (Neo4j results as JSON)                               │  │
│  │  • Vector context (Qdrant chunks with scores)                         │  │
│  │  • Context assembly (20k character limit)                             │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                   │                                         │
│                                   ▼                                         │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Node: SYNTHESIZE (with EXECUTION RAILS)                              │  │
│  │  • EXECUTION RAILS:                                                  │  │
│  │    - LLM prompt safety (injection detection)                         │  │
│  │    - Execution time limits and monitoring                            │  │
│  │    - Tool output validation and sanitization                          │  │
│  │    - Sensitive information redaction                                  │  │
│  │  • Gemini 3 Flash invocation (temp 0.1)                               │  │
│  │  • Signature list handling (extract readable text)                     │  │
│  │  • 429 fallback (extractive answer from context)                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      OUTPUT RAILS (Final Validation)                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  • Harmful content detection (violence, illegal activities)            │  │
│  │  • Sensitive information filtering (SSN, credit cards, emails)         │  │
│  │  • Injection pattern removal                                           │  │
│  │  • Response quality scoring (relevance, completeness)                  │  │
│  │  • Source attribution validation                                      │  │
│  │  • Answer quality checks (accuracy, hedging detection)               │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FINAL RESPONSE                                      │
│  • Sanitized answer                                                        │
│  • Rails trace (input → retrieval → execution → output)                   │
│  • Source attribution                                                     │
│  • Quality metrics                                                         │
│  • Cache metadata                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Dual-Layer Guardrails Architecture

### 3.1 Content Guardrails (Business Logic)
**Location**: `src/guardrails_config/rails.co` + `src/guardrails/fin_guardrails.py`

**Purpose**: Determines **WHAT** questions the system should answer

**Components**:
- **Topic Classification**: Financial vs off-topic detection
- **Intent Analysis**: RELATIONAL/FACTUAL/SEMANTIC classification
- **Domain Scope**: Indian companies × Chinese partnerships only
- **Canonical Matching**: Deterministic similarity ≥0.85 for known patterns
- **Gemini Classifier**: Fallback LLM-based classification (temp=0)

**Examples from rails.co**:
```colang
define user ask off topic
  "tell me a joke"
  "capital of france"
  "what is 2+2"
  "poem about love"

define user ask financial question
  "relationship between JSW and Chery"
  "Reliance CATL partnership"
  "Bharti Haier deal"
```

**Flow**:
```
Query → LOAD rails.co → SCOPE scan (CSV terms) → CANONICAL match → GEMINI classify → FLOW selection → BOT action
```

### 3.2 Technical Rails (Security Safety)
**Location**: `src/rails/` (input_rails.py, retrieval_rails.py, execution_rails.py, output_rails.py)

**Purpose**: Determines **HOW** to safely execute operations

**Components**:

#### Input Rails (`src/rails/input_rails.py`)
- Query length validation (min/max limits)
- Injection pattern detection (SQL, XSS, script injection)
- Character safety checks (null bytes, control characters)
- Query sanitization (whitespace normalization)
- Query structure analysis (complexity, financial terms, entity detection)

#### Retrieval Rails (`src/rails/retrieval_rails.py`)
- Sensitive data request detection (PII, personal information)
- Query complexity analysis and limiting
- Scope control (full/limited/none access)
- Dynamic max-results adjustment based on complexity
- Retrieval result validation and quality filtering
- Sensitive data filtering in results

#### Execution Rails (`src/rails/execution_rails.py`)
- Tool invocation control (blocked operations list)
- Dangerous parameter detection
- LLM prompt safety (injection detection)
- Execution time limits and monitoring
- Resource usage monitoring
- Tool output validation and sanitization
- Sensitive information redaction

#### Output Rails (`src/rails/output_rails.py`)
- Harmful content detection (violence, illegal activities)
- Sensitive information filtering (SSN, credit cards, emails, phones)
- Injection pattern removal
- Response quality scoring
- Source attribution validation
- Answer quality checks (relevance, completeness, accuracy)

**Flow**:
```
Input Rails → Content Guardrails → Retrieval Rails → Execution Rails → Output Rails
```

---

## 4. Rails Orchestrator

**Location**: `src/rails/rails_orchestrator.py`

**Purpose**: Unified coordination of all technical rails

**Responsibilities**:
- Coordinate all rails in sequence
- Provide single interface for RAG system
- Comprehensive tracing and monitoring
- Error handling and graceful degradation
- Individual rail execution methods

**Key Methods**:
```python
execute_full_rails_flow(query, intent, plan, retriever_func, llm_func, context)
execute_input_rails_only(query)
execute_retrieval_rails_only(query, intent, plan, top_k)
execute_output_rails_only(response, context)
get_rails_status()
```

**Integration Points**:
- **API Layer**: Applied before/after query processing
- **Orchestrator**: Integrated into retrieval and synthesis nodes
- **Health Monitoring**: Status available via health endpoints

---

## 5. Updated Data Flow Examples

### 5.1 Normal Financial Query (All Rails Pass)
```
Query: "What is the relationship between JSW Group and Chery Automobile?"

1. INPUT RAILS:
   - Valid length (42 chars < 2000 limit)
   - No injection patterns detected
   - Sanitized: "What is the relationship between JSW Group and Chery Automobile?"
   - ✅ PASSED

2. CONTENT GUARDRAILS:
   - SCOPE scan: hits [jsw, chery, automobile]
   - CANONICAL match: no exact match
   - GEMINI classify: "ask financial question"
   - FLOW: handle financial question → execute financial_rag
   - ✅ ALLOWED

3. CACHE:
   - Response cache: MISS (first time)
   - Semantic cache: MISS
   - Continue to RAG pipeline

4. UNDERSTAND:
   - Intent: RELATIONAL (contains "relationship")
   - Entities: [What, JSW, Group, Chery, Automobile]
   - Plan: HYBRID (graph + vector)

5. RETRIEVAL RAILS:
   - No sensitive data patterns detected
   - Complexity: low (1 complexity indicator)
   - Scope: full access
   - Max results: 8
   - ✅ ALLOWED

6. RETRIEVE:
   - Neo4j: 3 relationships (PARTNERS_WITH, LICENSES_TECHNOLOGY_FROM)
   - Qdrant: 6 chunks with scores
   - Results validated: all high quality

7. BUILD CONTEXT:
   - Memory: empty (first query)
   - Graph context: 3 nodes with relationships
   - Vector context: 6 chunks
   - Total: 4,245 characters

8. EXECUTION RAILS:
   - Prompt: safe (no injection patterns)
   - Temperature: 0.1 (within range)
   - Length: 4,300 chars (< 20,000 limit)
   - ✅ ALLOWED

9. SYNTHESIZE:
   - Gemini 3 Flash invocation
   - Response: "Technology Licensing — JSW sources technology from Chery Automobile..."

10. OUTPUT RAILS:
    - No harmful content detected
    - No sensitive information found
    - Quality score: 1.0
    - Source attribution: validated
    - ✅ PASSED

11. FINAL RESPONSE:
    - Sanitized answer
    - Rails trace included
    - Sources cited
    - Cache upsert
```

### 5.2 Malicious Query (Rails Block)
```
Query: "<script>alert('xss')</script> What is JSW?"

1. INPUT RAILS:
   - Injection pattern detected: <script[^>]*>.*?</script>
   - ❌ BLOCKED
   - Reason: "Potentially malicious pattern detected"
   - Stopped at API layer (no processing cost)
```

### 5.3 Sensitive Data Request (Retrieval Rails Block)
```
Query: "What are the personal phone numbers of executives?"

1. INPUT RAILS:
   - ✅ PASSED (valid query structure)

2. CONTENT GUARDRAILS:
   - SCOPE scan: hits [phone, numbers]
   - GEMINI classify: "ask financial question" (misclassification)
   - ✅ ALLOWED (content rails allow it)

3. RETRIEVAL RAILS:
   - Sensitive pattern detected: phone\s+number
   - ❌ BLOCKED
   - Reason: "Sensitive data pattern detected"
   - Scope: none
   - Safe fallback message returned
```

### 5.4 Off-Topic Query (Content Guardrails Block)
```
Query: "tell me a joke"

1. INPUT RAILS:
   - ✅ PASSED (valid query structure)

2. CONTENT GUARDRAILS:
   - CANONICAL match: "tell me a joke" (0.95 similarity)
   - Decider: rails.co canonical-example match
   - FLOW: handle off topic
   - ❌ BLOCKED
   - Reason: "ask off topic"
   - Bot message: Refusal with scope explanation
   - 0 DB/LLM cost
```

---

## 6. UI Layer — Streamlined (`src/streamlit_app.py`)

**Theme fix (Sep 13):** removed `st.chat_input` fixed-position overlap with Deploy header; now `text_area + Send` inside Chat tab; `block-container` top padding; `3×2` card grid (was 6-in-row squeeze); `overflow-wrap:anywhere` for badges/answers.

**Hero:** gradient `FinGraphRAG` + subtitle + badges (Hybrid, 105 Edges, 532 Vecs, Gemini 3 Flash, Dual Guardrails, Upstash).

**Cards (3×2):**
- Hybrid Retrieval
- Knowledge Graph (629/105)
- Vector Search
- Gemini Synthesis
- Dual Guardrails (Content + Technical)
- 3-Layer Cache

**Tabs:**
- **Chat** — chips (JSW×Chery, Bharti×Haier, CATL, Dixon×Vivo), `st.chat_message` history, badges (Cache HIT/RAG, Guardrail block, Rails block), `answer-box`, expanders: Guardrail trace · Rails trace · Retrieval (Cypher, 4 graph nodes + 4 chunks) · Context. Latency + source count caption. Fallback warning on 429.
- **Graph Explorer** — live `MATCH count`, bar by rel type, 12-row edge table, schema code. Proves `MATCH (JSW)-[:LICENSES_TECHNOLOGY_FROM]->(Chery)` now works.
- **Cache Dashboard** — hit rate, hits/misses/saved, bar by layer, Upstash snippet, semantic test box, history table. Explains Response/Semantic/Prompt.
- **Rails Status** — new tab showing comprehensive rails configuration and status
- **Architecture** — ASCII diagram only + caption pointing to this file.

**Sidebar:**
- `System Status` (gemini/qdrant/neo4j/guardrails/rails_orchestrator/langsmith)
- `🔄 Retry` (bypasses 60s cooldown)
- Neo4j/Qdrant expanders with hints
- Upstash status + hit rate
- Rails configuration summary
- Queries/Turns counter

---

## 7. Orchestrator (`src/orchestrator.py`)

**State:** `GraphState {query, session_id, top_k, blocked, guard_*, intent, plan, graph_context, vector_context, sources, context, answer, retrieval_validation}`.

**Nodes:**
- `guard` (content guardrails) → conditional `blocked? synthesize : understand`
- `understand` (REL if relationship/between/partner, FACT if what is/which/ticker/code, else SEM; plan HYBRID/LOCAL/GLOBAL; entities regex)
- `retrieve` (with retrieval rails - Company-first Cypher + FinancialEntity fallback, Qdrant `query_points`, unified sources, vector-only fallback, result validation)
- `build_context` (memory + Graph json + Document)
- `synthesize` (with execution rails - blocked→refusal else Gemini invoke → `_extract_text` handling signature list else `_fallback_answer` on 429/RESOURCE_EXHAUSTED)

**`query()`** returns `trace{step_0_guardrails, step_1_understand{intent/entities/domain/plan}, step_2_graph{cypher/params/database/nodes}, step_3_vector{collection/chunks}, step_4_context{chars}, step_5_rails{input/retrieval/execution/output}}` + `guard_trace` + `rails_trace`.

**`health()/health_detail()/reconnect()`** — adds `neo4j_detail/qdrant_detail` with hints, `rails_path/exists`, `rails_orchestrator_status`, `gemini_model`.

---

## 8. API Layer (`src/api.py`)

**Endpoints:**
- `GET /health` — System health status including rails
- `GET /rails/status` — Detailed rails configuration and status
- `POST /query` — Main query endpoint with input/output rails
- `DELETE /memory/{session_id}` — Clear conversation memory

**Rails Integration:**
- Input validation before query processing
- Output validation after response generation
- Rails trace included in responses
- Comprehensive error handling

---

## 9. Data Storage

### Neo4j `src/tools/neo4j_tools.py`
Driver `neo4j+s://5a76f90e` with `+ssc` fallback for Windows `CERTIFICATE_VERIFY_FAILED`; home-DB auto-discovery (`5a76f90e`); `_ensure_driver(60s cooldown)` + `reconnect()` from sidebar; `_stable_key(company_code|name)` (fixes old `hash()` randomization); `search()` Company-first with `OPTIONAL MATCH (n)-[r]->(neighbor)` (previously 0 rels for JSW); `upsert_rows` (FinancialEntity MERGE) + `upsert_with_edges` (MERGE `:Company` + typed `PARTNERS_WITH/LICENSES_TECHNOLOGY_FROM/HAS_STAKE_IN/...` via `REL_TYPE_MAP`, idempotent grouped by type). Migration `scripts/add_edges.py --skip_qdrant` gave `316→629 nodes, 0→105 rels, qdrant 532→532`.

### Qdrant `src/tools/qdrant_tools.py`
`QdrantClient(timeout 120)` + `GoogleGenerativeAIEmbeddings`. `health_detail` + `ensure_collection`; `_embed_batch` retry `35s·attempt` on 429; `upsert` now **deterministic** `uuid5(sha256(text|source|row))` (was `uuid4` → 532 points for 320 rows) + `batch 5 + sleep 2`; `search` embed_query → query_points.

---

## 10. Caching — 3 Layers (`src/tools/semantic_cache.py`)

**Response Cache** — `norm(query)` exact → instant.
**Semantic Cache** — **Upstash Vector** `classic-lioness-60363-us1-vector.upstash.io` (`upstash-vector`) else local 384-d hashed fallback; cosine ≥ `CACHE_THRESHOLD 0.88` (e.g. *"JSW Chery deal?"* hits *"What is JSW Group and Chery relationship?"*). Upsert on each miss, hit skips RAG.
**Prompt Cache** — `hash(context+question)` → LLM output (implemented as response cache extension).

**UI:** `MultiLayerCache` stats `hits/misses/response_hits/semantic_hits/prompt_hits/total_saved_ms` shown in sidebar + Cache tab bar/history/test box. `Cache HIT · semantic 0.96` badge in chat. Install: `pip install upstash-vector`.

---

## 11. AI/ML & Memory

**Gemini:** `gemini-3-flash-preview` (`GEMINI_MODEL`, alias `GEMINI_MODEL_NAME`) — free tier `gemini-3.5-flash` exhausted at 20/d, `_fallback_answer` keeps 429 from throwing; `upstash` not using Gemini for embeddings in cache fallback.

**Embeddings:** `models/gemini-embedding-001` 3072-d.

**Memory:** `src/memory/conversation_memory.py` window `MEMORY_WINDOW_SIZE=10`, per `session_id`.

---

## 12. Config (`src/config/settings.py`, `src/.env`)

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
| `MAX_QUERY_LENGTH` | `2000` | Input rails |
| `DEFAULT_MAX_RESULTS` | `10` | Retrieval rails |
| `MAX_RESPONSE_LENGTH` | `5000` | Output rails |

---

## 13. Operations

```powershell
# Streamlit :8501 (now text_area+Send, 3×2 cards, no overlap)
python -m streamlit run src/streamlit_app.py --server.headless true --server.port 8501

# FastAPI
python -m src.main serve --port 8000

# One-shot
python -m src.main ask "What is the relationship between JSW Group and Chery Automobile?" --session-id demo

# Edges (idempotent, no Qdrant dup)
python scripts/add_edges.py

# NeMo (content guardrails only)
NEMOGUARDRAILS_LLM_FRAMEWORK=langchain nemoguardrails chat --config src/guardrails_config

# Check rails status
curl http://localhost:8000/rails/status
```

**Health:** sidebar `System Status` + deep dives + `🔄 Retry` + `Upstash: ✓ connected` + `Hit rate` + `Rails Status`.

---

## 14. Security & Compliance

### 14.1 Content Protection
- **Business Scope**: Only Indian companies × Chinese partnerships
- **Topic Filtering**: Off-topic queries blocked (0 cost)
- **Intent Classification**: RELATIONAL/FACTUAL/SEMANTIC detection
- **Domain Enforcement**: CSV-based scope validation

### 14.2 Technical Security
- **Input Protection**: SQL injection, XSS, command injection prevention
- **Retrieval Control**: PII protection, sensitive data filtering
- **Execution Safety**: Prompt injection prevention, resource limits
- **Output Protection**: Harmful content filtering, sensitive data redaction

### 14.3 Compliance Features
- **Data Minimization**: Only retrieve relevant data
- **Access Control**: Scope-based retrieval limits
- **Audit Trail**: Comprehensive tracing and monitoring
- **Privacy Protection**: PII detection and filtering

---

## 15. Monitoring & Observability

### 15.1 Rails Tracing
Each query includes comprehensive rails trace:
- **Input Rails**: Validation decisions, sanitization applied
- **Content Guardrails**: Topic classification, flow selection
- **Retrieval Rails**: Scope decisions, result filtering
- **Execution Rails**: Safety decisions, monitoring data
- **Output Rails**: Quality scores, filtering applied

### 15.2 Health Monitoring
- Component status (Neo4j, Qdrant, Gemini, Rails)
- Detailed health information (connection strings, configuration)
- Rails configuration status
- Cache performance metrics

### 15.3 LangSmith Integration
- Traceable retrieval operations
- Traceable synthesis operations
- Performance monitoring
- Error tracking

---

## 16. Known State & Limitations

* Qdrant 532 reflects old `uuid4` dupes (correct deterministic re-ingest would be ~320); kept to avoid data loss, future upserts are idempotent.
* Neo4j 629 = legacy 316 FinancialEntity + 313 Company (Company nodes enable traversal; FinancialEntity kept for provenance).
* BYD vs BYD Co remain separate Company nodes (raw partner normalization could merge them).
* Content guardrails may misclassify edge cases (Gemini classifier fallback handles most).
* Technical rails use pattern-based detection (may need tuning for sophisticated attacks).
* No authentication/authorization implemented (per user preference).

---

## 17. Future Enhancements

### Rails Improvements
- Machine learning-based anomaly detection
- Adaptive pattern learning from attacks
- Custom rule configuration interface
- A/B testing for rail policies

### System Enhancements
- Authentication/authorization layers (if needed)
- Advanced rate limiting
- Real-time alerting for security events
- Enhanced logging and audit trails

### Performance Optimizations
- Parallel rail execution where safe
- Cached rail decisions for similar queries
- Optimized pattern matching algorithms
- Reduced latency for validation steps

---

## 18. Summary

FinGraphRAG now implements a **comprehensive dual-layer guardrails system**:

1. **Content Guardrails** (NeMo/Colang): Ensure the system only answers relevant financial questions about Indian companies and their Chinese partners
2. **Technical Rails** (Custom Python): Ensure all operations are executed safely without security vulnerabilities, data leaks, or harmful content

The system provides **defense-in-depth** protection while maintaining performance, usability, and the ability to answer legitimate financial research queries effectively. All components are monitored, traced, and observable through the comprehensive UI and API endpoints.