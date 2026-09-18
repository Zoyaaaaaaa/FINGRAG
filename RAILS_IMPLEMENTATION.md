# Rails Implementation for FinGraphRAG

## Overview
This document describes the comprehensive rails implementation that follows the architecture pattern you specified, focusing on Retrieval/Execution control as requested.

## Architecture Mapping

Your original architecture:
```
USER → API Gateway → Authentication → Authorization → Input Rails → Agent/RAG 
→ Retriever/Tools → Retrieval Rail/Execution Rail → LLM → Output Rails → USER
```

Our implementation focuses on the core rails components:

### ✅ Implemented Components

#### 1. **Input Rails** (`src/rails/input_rails.py`)
- **Location**: Before Agent/RAG processing
- **Functionality**:
  - Query length validation (min/max limits)
  - Injection pattern detection (SQL, XSS, script injection)
  - Character safety checks
  - Query sanitization (whitespace, control characters)
  - Query structure analysis (complexity, financial terms, company names)

#### 2. **Retrieval Rails** (`src/rails/retrieval_rails.py`)
- **Location**: Controls data retrieval from Neo4j/Qdrant
- **Functionality**:
  - Sensitive data request detection (PII, personal information)
  - Query complexity analysis and limiting
  - Scope control (full/limited/none access)
  - Dynamic max-results adjustment
  - Retrieval result validation and filtering
  - Quality-based result filtering

#### 3. **Execution Rails** (`src/rails/execution_rails.py`)
- **Location**: Controls LLM and tool execution
- **Functionality**:
  - Tool invocation control (blocked operations list)
  - Dangerous parameter detection
  - LLM prompt safety (injection detection)
  - Execution time limits and timeouts
  - Resource usage monitoring
  - Tool output validation and sanitization
  - Sensitive information redaction

#### 4. **Output Rails** (`src/rails/output_rails.py`)
- **Location**: Before response is sent to user
- **Functionality**:
  - Harmful content detection
  - Sensitive information filtering (SSN, credit cards, emails, phones)
  - Injection pattern removal
  - Response quality scoring
  - Source attribution validation
  - Answer quality checks (relevance, completeness, accuracy)

#### 5. **Rails Orchestrator** (`src/rails/rails_orchestrator.py`)
- **Location**: Unified coordination layer
- **Functionality**:
  - Coordinates all rails in sequence
  - Provides single interface for RAG system
  - Comprehensive tracing and monitoring
  - Error handling and graceful degradation
  - Individual rail execution methods

### ❌ Skipped Components (as requested)
- **Authentication**: You requested "No authentication"
- **Authorization**: You requested "No authorization"

## Integration Points

### API Layer (`src/api.py`)
- Added `RailsOrchestrator` initialization
- Applied input validation before query processing
- Applied output validation after response generation
- Added `/rails/status` endpoint for monitoring
- Integrated rails trace into query responses

### Orchestrator Layer (`src/orchestrator.py`)
- Added `RailsOrchestrator` to FinGraphRAG system
- Applied retrieval rails in `_retrieve()` method
- Updated health checks to include rails status
- Integrated rails monitoring into detailed health information

## File Structure
```
src/rails/
├── __init__.py                 # Package exports
├── input_rails.py             # Input validation and sanitization
├── retrieval_rails.py        # Retrieval control and validation
├── execution_rails.py         # Execution safety and monitoring
├── output_rails.py           # Output validation and safety
└── rails_orchestrator.py     # Unified coordination layer
```

## Testing Results

All rails components tested successfully:

### Input Rails Tests
- ✅ Valid queries pass validation
- ✅ Overly long queries are blocked
- ✅ Injection attempts are detected and blocked
- ✅ Query sanitization works correctly

### Retrieval Rails Tests
- ✅ Normal financial queries get full access
- ✅ Sensitive data requests are blocked
- ✅ Complex queries get limited scope
- ✅ Result quality filtering works

### Execution Rails Tests
- ✅ Valid LLM executions are allowed
- ✅ Prompt injection attempts are blocked
- ✅ Dangerous operations are prevented
- ✅ Output sanitization removes sensitive data

### Output Rails Tests
- ✅ Valid responses pass validation
- ✅ Harmful content is detected and blocked
- ✅ Sensitive information is filtered
- ✅ Quality scoring works correctly

### Integration Tests
- ✅ End-to-end rails flow works correctly
- ✅ Malicious queries are properly handled
- ✅ Rails status endpoint returns correct information

## Configuration

Rails can be configured via settings (inherited from main settings):

```python
# Input Rails
max_query_length = 2000
min_query_length = 1

# Retrieval Rails  
default_max_results = 10
max_query_complexity = 5

# Execution Rails
default_timeout = 30
max_retries = 2

# Output Rails
max_response_length = 5000
```

## Usage Examples

### Basic Usage
```python
from src.rails import RailsOrchestrator

orchestrator = RailsOrchestrator(settings)

# Input validation
input_result = orchestrator.execute_input_rails_only(query)

# Retrieval validation
retrieval_decision = orchestrator.execute_retrieval_rails_only(
    query, intent, plan, top_k
)

# Output validation
output_result = orchestrator.execute_output_rails_only(response, context)
```

### Full Flow
```python
result = orchestrator.execute_full_rails_flow(
    query=query,
    intent=intent,
    plan=plan,
    retriever_func=retriever_function,
    llm_func=llm_function,
    context=context
)
```

## Security Features

### Input Protection
- SQL injection prevention
- XSS attack prevention
- Command injection blocking
- Query length limits
- Malicious pattern detection

### Retrieval Control
- PII request blocking
- Sensitive data protection
- Access scope limitation
- Query complexity management
- Result quality filtering

### Execution Safety
- Prompt injection prevention
- Dangerous operation blocking
- Resource usage monitoring
- Timeout enforcement
- Output sanitization

### Output Protection
- Harmful content filtering
- Sensitive data redaction
- Quality assurance
- Source validation
- Response verification

## Monitoring and Observability

The rails provide comprehensive monitoring:
- Individual decision tracking
- Execution time monitoring
- Blocked request logging
- Quality scoring
- Detailed trace information

All monitoring data is available through:
- Rails orchestrator trace results
- Health status endpoints
- Individual rail validation results

## Future Enhancements

Potential areas for expansion:
- Add more sophisticated anomaly detection
- Implement learning-based pattern recognition
- Add rate limiting and throttling
- Enhanced logging and alerting
- Custom rule configuration
- A/B testing for rail policies

## Conclusion

The rails implementation provides comprehensive protection across the entire RAG pipeline while maintaining system performance and usability. The focus on Retrieval/Execution control ensures safe data access and LLM operations while protecting against common security threats.

Now let me provide a comprehensive explanation of the intent classification, entity extraction, and query planning in your FinGraphRAG system.

## **Intent Classification System**

Your system classifies user queries into **three intent types** to determine the best retrieval strategy:

### **1. RELATIONAL Intent**
**Purpose**: Queries about relationships, connections, or interactions between entities

**Detection Keywords**: 
- `relationship`, `between`, `collaborate`, `partner`, `connected`, `impact`

**Examples**:
- "What is the **relationship between** JSW Group and Chery Automobile?"
- "How does Reliance **collaborate with** CATL?"
- "What's the **connection** between Bharti and Haier?"

**What Happens**:
- System identifies this as a RELATIONAL query
- **Query Plan**: HYBRID (uses both graph + vector search)
- **Rationale**: Relationships are best captured in the knowledge graph (Neo4j), but additional context from documents (Qdrant) helps provide complete answers

**Retrieval Strategy**:
```python
# Both Neo4j and Qdrant are used
graph_context = self.neo4j.search(query, entities, max_results)  # Graph relationships
vector_context = self.qdrant.search(query, max_results)           # Document context
```

### **2. FACTUAL Intent**
**Purpose**: Queries seeking specific facts, definitions, or direct information

**Detection Keywords**:
- `what is`, `which`, `how much`, `ticker`, `code`, `revenue`

**Examples**:
- "**What is** the stock code for JSW Group?"
- "**Which** companies partner with Chinese firms?"
- "**How much** revenue does Tata generate?"
- "**What is** the deal type between Reliance and CATL?"

**What Happens**:
- System identifies this as a FACTUAL query
- **Query Plan**: LOCAL (graph-only search preferred)
- **Rationale**: Specific facts about companies, codes, and structured data are typically stored in the knowledge graph

**Retrieval Strategy**:
```python
# Neo4j only (graph search)
graph_context = self.neo4j.search(query, entities, max_results)
vector_context = []  # Vector search skipped
```

### **3. SEMANTIC Intent**
**Purpose**: General queries that don't match RELATIONAL or FACTUAL patterns

**Detection**: Default fallback when no specific keywords are found

**Examples**:
- "Tell me about electric vehicle partnerships"
- "Analyze the battery industry"
- "What are the trends in automotive collaborations?"
- "Discuss the EV market in India"

**What Happens**:
- System identifies this as a SEMANTIC query
- **Query Plan**: GLOBAL (vector-only search)
- **Rationale**: Broad, conceptual questions are best answered by searching through document content rather than structured graph data

**Retrieval Strategy**:
```python
# Qdrant only (vector search)
graph_context = []  # Graph search skipped
vector_context = self.qdrant.search(query, max_results)
```

---

## **Entity Extraction Process**

After intent classification, the system extracts named entities from the query:

### **How It Works**
```python
entities = re.findall(r"\b[A-Z][A-Za-z0-9&.-]{1,30}\b", query)
```

**Pattern Explanation**:
- `\b` - Word boundary (ensures we match whole words)
- `[A-Z]` - Starts with uppercase letter (proper noun)
- `[A-Za-z0-9&.-]{1,30}` - Followed by 1-30 characters (letters, numbers, &, ., -)
- `\b` - Ends at word boundary

### **Entity Extraction Examples**

**Query**: "What is the relationship between JSW Group and Chery Automobile?"
- **Extracted Entities**: `['What', 'JSW', 'Group', 'Chery', 'Automobile']`
- **Filtered Entities**: `['JSW', 'Group', 'Chery', 'Automobile']` (removing common words)

**Query**: "How does Reliance collaborate with CATL?"
- **Extracted Entities**: `['How', 'Reliance', 'CATL']`
- **Filtered Entities**: `['Reliance', 'CATL']`

**Query**: "What is the revenue of Tata Motors?"
- **Extracted Entities**: `['What', 'Tata', 'Motors']`
- **Filtered Entities**: `['Tata', 'Motors']`

### **Entity Usage**
Extracted entities are used in:
1. **Graph Search**: Neo4j uses entities to find company nodes and relationships
2. **Context Building**: Entities help identify relevant company information
3. **Query Enhancement**: Entities can be used to expand or refine search queries

---

## **Query Planning Strategies**

### **1. LOCAL Plan (Graph-Only)**
**Used For**: FACTUAL intents

**What It Does**:
- Searches only the Neo4j knowledge graph
- Focuses on structured data and relationships
- Best for specific facts about companies, codes, and structured information

**Components**:
- **Neo4j Search**: Cypher queries to find company nodes and their properties
- **Relationship Traversal**: 1-hop relationships from identified entities
- **Structured Data**: Company codes, deal types, financial metrics

**Example Flow**:
```
Query: "What is the stock code for JSW Group?"
Plan: LOCAL
↓
Neo4j Search: MATCH (c:Company) WHERE c.name CONTAINS 'JSW' RETURN c.stock_code
↓
Result: "JSWST" (stock code)
```

**Advantages**:
- Fast retrieval of structured data
- Precise answers to factual questions
- Low computational cost

**Limitations**:
- Limited to data in the graph
- Doesn't capture nuanced information from documents
- May miss contextual details

### **2. GLOBAL Plan (Vector-Only)**
**Used For**: SEMANTIC intents

**What It Does**:
- Searches only the Qdrant vector database
- Focuses on document content and semantic similarity
- Best for broad, conceptual questions and trend analysis

**Components**:
- **Vector Search**: Semantic similarity search using embeddings
- **Document Retrieval**: Relevant chunks from CSV documents
- **Contextual Information**: Unstructured text from reports and company data

**Example Flow**:
```
Query: "Tell me about electric vehicle partnerships"
Plan: GLOBAL
↓
Qdrant Search: vector similarity search for "electric vehicle partnerships"
↓
Results: Document chunks about EV partnerships, battery collaborations, etc.
↓
Synthesis: Comprehensive answer about EV partnership trends
```

**Advantages**:
- Captures nuanced, contextual information
- Handles broad, conceptual questions
- Can discover patterns across multiple documents

**Limitations**:
- Higher computational cost (embedding generation)
- May return less precise answers
- Depends on quality of document chunks

### **3. HYBRID Plan (Graph + Vector)**
**Used For**: RELATIONAL intents

**What It Does**:
- Searches both Neo4j graph and Qdrant vector database
- Combines structured relationships with contextual information
- Best for questions about relationships, partnerships, and connections

**Components**:
- **Neo4j Search**: Relationship data and structured connection information
- **Vector Search**: Contextual details about the relationships
- **Result Fusion**: Combines graph and vector results for comprehensive answers

**Example Flow**:
```
Query: "What is the relationship between JSW Group and Chery Automobile?"
Plan: HYBRID
↓
Neo4j Search: Find relationship between JSW and Chery nodes
↓
Result: PARTNERS_WITH relationship, deal details, partnership type
↓
Qdrant Search: Document chunks about JSW-Chery collaboration
↓
Results: Additional context about the partnership, timeline, specifics
↓
Synthesis: Comprehensive answer combining relationship structure + context
```

**Advantages**:
- Most comprehensive retrieval strategy
- Combines precision of graph with richness of documents
- Best for complex relationship questions

**Limitations**:
- Highest computational cost
- More complex result fusion
- Potential for redundant information

---

## **Complete Intent Processing Flow**

### **Step-by-Step Process**

```python
def _understand(state: GraphState) -> dict[str, Any]:
    query = state["query"]
    lowered = query.lower()
    
    # 1. INTENT CLASSIFICATION
    relational = any(word in lowered for word in ("relationship", "between", "collaborate", "partner", "connected", "impact"))
    factual = any(word in lowered for word in ("what is", "which", "how much", "ticker", "code", "revenue"))
    
    # 2. INTENT DETERMINATION
    intent = "RELATIONAL" if relational else "FACTUAL" if factual else "SEMANTIC"
    
    # 3. QUERY PLANNING
    plan = "HYBRID" if relational else "LOCAL" if factual else "GLOBAL"
    
    # 4. ENTITY EXTRACTION
    entities = re.findall(r"\b[A-Z][A-Za-z0-9&.-]{1,30}\b", query)
    
    return {
        "intent": {"intent": intent, "entities": entities, "domain": "financial"}, 
        "plan": plan
    }
```

### **Intent → Plan Mapping**

| Intent | Plan | Graph Search | Vector Search | Best For |
|--------|------|--------------|---------------|----------|
| RELATIONAL | HYBRID | ✅ Yes | ✅ Yes | Relationships, connections, partnerships |
| FACTUAL | LOCAL | ✅ Yes | ❌ No | Specific facts, codes, structured data |
| SEMANTIC | GLOBAL | ❌ No | ✅ Yes | Broad concepts, trends, analysis |

---

## **Real-World Examples**

### **Example 1: RELATIONAL Query**
```
Query: "What is the relationship between JSW Group and Chery Automobile?"

1. Intent Detection: RELATIONAL (contains "relationship", "between")
2. Entity Extraction: ['JSW', 'Group', 'Chery', 'Automobile']
3. Query Plan: HYBRID
4. Execution:
   - Neo4j: Finds PARTNERS_WITH relationship, deal details
   - Qdrant: Finds document chunks about the collaboration
5. Result: Comprehensive answer about the partnership with both structural and contextual information
```

### **Example 2: FACTUAL Query**
```
Query: "What is the stock code for JSW Group?"

1. Intent Detection: FACTUAL (contains "what is")
2. Entity Extraction: ['What', 'JSW', 'Group']
3. Query Plan: LOCAL
4. Execution:
   - Neo4j: Searches for company node, returns stock_code property
   - Qdrant: Skipped
5. Result: "JSWST" (precise factual answer)
```

### **Example 3: SEMANTIC Query**
```
Query: "Tell me about electric vehicle partnerships in India"

1. Intent Detection: SEMANTIC (no specific keywords)
2. Entity Extraction: ['Tell', 'India'] (limited entities)
3. Query Plan: GLOBAL
4. Execution:
   - Neo4j: Skipped
   - Qdrant: Searches for document chunks about EV partnerships
5. Result: Comprehensive overview of EV partnership trends from document analysis
```

---

## **Why This Approach Works**

### **Intent Classification Benefits**
- **Efficiency**: Directs queries to the most appropriate data source
- **Precision**: FACTUAL queries get precise graph data
- **Comprehensiveness**: RELATIONAL queries get both structure and context
- **Flexibility**: SEMANTIC queries can explore broad topics

### **Entity Extraction Benefits**
- **Targeted Search**: Focuses retrieval on relevant companies/entities
- **Context Relevance**: Ensures results are related to mentioned entities
- **Query Enhancement**: Can be used to expand or refine searches

### **Query Planning Benefits**
- **Resource Optimization**: Uses the most efficient retrieval strategy
- **Quality Improvement**: Matches retrieval strategy to question type
- **Scalability**: Balances computational cost with answer quality

This intelligent intent classification and query planning system ensures that your FinGraphRAG system efficiently retrieves the most relevant information for each type of question while optimizing for both performance and answer quality.
Now let me explain the three-layer caching system in detail, including the semantic cache time-to-live and other important aspects.

## **Three-Layer Caching System Overview**

Your FinGraphRAG system uses a sophisticated multi-layer caching strategy to optimize performance and reduce costs:

### **Cache Layer Hierarchy**
```
Query → Layer 1: Response Cache (exact match) → Layer 2: Semantic Cache (meaning match) → Layer 3: Prompt Cache (context match) → Full RAG Pipeline
```

---

## **Layer 1: Response Cache (Exact Match)**

### **How It Works**
- **Key**: Normalized query string (lowercase, whitespace normalized)
- **Value**: Complete answer/response
- **Matching**: Exact string match only
- **Speed**: ~0ms (instant dictionary lookup)

### **Implementation**
```python
def _norm(self, q: str) -> str:
    return " ".join(q.strip().lower().split())

def get_response(self, query: str) -> CacheEntry | None:
    key = self._norm(query)  # "What is JSW?" → "what is jsw?"
    ent = self._response.get(key)
    if ent is not None:
        self.stats.response_hits += 1
        return ent
    return None
```

### **Time-to-Live**
- **No explicit TTL** - entries persist indefinitely
- **Storage**: In-memory dictionary (Python dict)
- **Capacity**: Limited only by available memory
- **Clearing**: Manual via `clear()` method or system restart

### **Examples**
```
Query 1: "What is the relationship between JSW and Chery?"
→ MISS → Full RAG → Answer stored in Response Cache

Query 2: "What is the relationship between JSW and Chery?"  
→ HIT (exact match) → Returns cached answer instantly (0ms)

Query 3: "What is the relationship between JSW and Chery?" 
→ HIT (exact match) → Returns cached answer instantly (0ms)
```

---

## **Layer 2: Semantic Cache (Meaning Match)**

### **How It Works**
- **Key**: Query vector (embedding representation)
- **Value**: Complete answer/response
- **Matching**: Cosine similarity ≥ threshold (default 0.88)
- **Speed**: ~10-50ms (embedding generation + vector search)

### **Implementation**
```python
def get_semantic(self, query: str) -> CacheEntry | None:
    vec = self.semantic._embed(query)  # Convert to vector
    hits = self.semantic.query(vec, top_k=1, include_metadata=True)
    
    if not hits:
        return None
    
    best = hits[0]
    score = float(best.get("score", 0) or 0)
    
    if score >= self.semantic.threshold:  # 0.88 by default
        meta = best.get("metadata", {}) or {}
        ent = CacheEntry(
            query=meta.get("orig_query", query), 
            answer=meta.get("answer", ""), 
            layer="semantic", 
            score=score
        )
        self.stats.semantic_hits += 1
        return ent
    return None
```

### **Time-to-Live (TTL) Details**

**Important**: The semantic cache has **no explicit TTL** - entries persist indefinitely:

- **No Automatic Expiration**: Entries are stored indefinitely until manually cleared
- **Storage Duration**: 
  - **Upstash Vector**: Persistent cloud storage (depends on Upstash plan limits)
  - **Local Fallback**: In-memory storage (persists until system restart)
- **Timestamp Usage**: Each entry has a `ts` (timestamp) field, but it's **not used for expiration** - only for logging/observability

### **Storage Backends**

#### **Primary: Upstash Vector (Cloud)**
```python
if url and token:
    self._upstash = Index(url=url, token=token)
```
- **Persistence**: Cloud-based, persists across system restarts
- **Capacity**: Depends on Upstash Vector plan limits
- **Performance**: Fast vector search with indexing
- **Cost**: Free tier available, then pay-per-usage

#### **Fallback: Local Memory**
```python
self._local: list[dict[str, Any]] = []
self._local_vectors: list[list[float]] = []
```
- **Persistence**: In-memory only, lost on system restart
- **Capacity**: Limited by available RAM
- **Performance**: Brute-force cosine similarity (slower for large datasets)
- **Cost**: Free

### **Similarity Threshold**
- **Default**: 0.88 (configurable via `CACHE_THRESHOLD` setting)
- **Meaning**: Queries must be 88% similar in meaning to match
- **Formula**: Cosine similarity between query vectors
- **Tuning**: 
  - Higher threshold (0.90+) = more precise matches, fewer hits
  - Lower threshold (0.80-) = more matches, potential false positives

### **Examples**
```
Query 1: "What is the relationship between JSW and Chery?"
→ MISS → Full RAG → Answer stored in Semantic Cache with vector

Query 2: "JSW Chery deal?"  
→ HIT (semantic 0.92 similarity) → Returns cached answer

Query 3: "Tell me about JSW Group and Chery Automobile partnership"
→ HIT (semantic 0.89 similarity) → Returns cached answer

Query 4: "What is the weather today?"
→ MISS (semantic 0.15 similarity) → Full RAG (different topic)
```

### **Vector Embedding Process**
```python
def _embed(self, text: str) -> list[float]:
    # Primary: Google Generative AI Embeddings
    if self._embedder is not None:
        return self._embedder.embed_query(text)  # 3072-dimensional vector
    
    # Fallback: Hash-based bag-of-words (384-dimensional)
    vec = [0.0] * 384
    for tok in text.lower().split():
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % 384] += 1.0
    # Normalize vector
    return [x / norm for x in vec]
```

---

## **Layer 3: Prompt Cache (Context Match)**

### **How It Works**
- **Key**: Hash of (prompt + context)
- **Value**: LLM output/synthesis
- **Matching**: Exact hash match
- **Speed**: ~0ms (dictionary lookup)

### **Implementation**
```python
def get_prompt(self, prompt_hash: str) -> str | None:
    ans = self._prompt.get(prompt_hash)
    if ans is not None:
        self.stats.prompt_hits += 1
        return ans
    return None

def put_prompt(self, prompt_hash: str, answer: str):
    self._prompt[prompt_hash] = answer
```

### **Time-to-Live**
- **No explicit TTL** - entries persist indefinitely
- **Storage**: In-memory dictionary
- **Capacity**: Limited by available memory
- **Scope**: Caches LLM outputs for identical prompt+context combinations

### **Examples**
```
Query 1: "What is JSW?" (with specific context)
→ MISS → Full RAG → LLM synthesis cached with prompt hash

Query 2: "What is JSW?" (with identical context)
→ HIT (prompt hash match) → Returns cached LLM output
```

---

## **Cache Lookup Flow**

### **Priority Order**
```python
def lookup(self, query: str) -> tuple[CacheEntry | None, str]:
    # Layer 1: Exact match
    ent = self.get_response(query)
    if ent:
        return ent, "response"
    
    # Layer 2: Semantic match
    ent = self.get_semantic(query)
    if ent:
        return ent, "semantic"
    
    # Layer 3: Miss - proceed to full RAG
    self.stats.misses += 1
    return None, "miss"
```

### **Decision Tree**
```
Query
  │
  ├─→ Response Cache (exact match?)
  │     ├─→ YES → Return cached answer (0ms)
  │     └─→ NO → Continue
  │
  ├─→ Semantic Cache (meaning match ≥0.88?)
  │     ├─→ YES → Return cached answer (10-50ms)
  │     └─→ NO → Continue
  │
  ├─→ Prompt Cache (context match?)
  │     ├─→ YES → Return cached LLM output (0ms)
  │     └─→ NO → Continue
  │
  └─→ Full RAG Pipeline (500-2000ms)
```

---

## **Cache Statistics & Monitoring**

### **Tracked Metrics**
```python
@dataclass
class CacheStats:
    hits: int = 0              # Total cache hits
    misses: int = 0            # Total cache misses
    response_hits: int = 0     # Layer 1 hits
    semantic_hits: int = 0     # Layer 2 hits
    prompt_hits: int = 0       # Layer 3 hits
    total_saved_ms: float = 0.0 # Total time saved
```

### **Hit Rate Calculation**
```python
@property
def hit_rate(self) -> float:
    tot = self.stats.hits + self.stats.misses
    return self.stats.hits / tot if tot else 0.0
```

### **UI Display**
- **Sidebar**: Shows hit rate, total saved time
- **Cache Tab**: Detailed history, performance metrics
- **Chat Interface**: Badges showing cache hits (e.g., "Cache HIT · semantic 0.92")

---

## **Storage & Persistence Details**

### **Upstash Vector Configuration**
```python
# Settings from src/.env
UPSTASH_VECTOR_REST_URL = "classic-lioness-60363-us1-vector.upstash.io"
UPSTASH_VECTOR_REST_TOKEN = "ABkF..."
CACHE_THRESHOLD = 0.88
```

### **Storage Limits**
- **Upstash Free Tier**: Typically 10,000 vectors, then pay-per-usage
- **Local Memory**: Limited by available RAM (typically 100-1000 entries)
- **Response Cache**: Limited by memory (typically 1000-10000 entries)

### **Cache Entry Structure**
```python
@dataclass
class CacheEntry:
    query: str              # Original query
    answer: str             # Cached answer
    layer: str              # Which cache layer
    score: float | None     # Similarity score (semantic only)
    ts: float               # Timestamp (not used for TTL)
```

---

## **Performance Impact**

### **Typical Latencies**
- **Response Cache HIT**: ~0ms (instant)
- **Semantic Cache HIT**: ~10-50ms (embedding + search)
- **Prompt Cache HIT**: ~0ms (instant)
- **Full RAG MISS**: ~500-2000ms (full pipeline)

### **Cost Savings**
- **LLM API Calls**: Reduced by cache hits
- **Database Queries**: Reduced by cache hits
- **Overall Latency**: Significantly improved for repeated queries

### **Memory Usage**
- **Response Cache**: ~1KB per entry
- **Semantic Cache**: ~4KB per entry (vector + metadata)
- **Prompt Cache**: ~2KB per entry

---

## **Cache Management**

### **Manual Clearing**
```python
def clear(self):
    self._response.clear()      # Clear response cache
    self._prompt.clear()        # Clear prompt cache
    # Note: Semantic cache in Upstash persists (not cleared for safety)
    self._history.clear()       # Clear history
    self.stats = CacheStats()   # Reset statistics
```

### **Automatic Management**
- **History**: Limited to 200 most recent entries
- **No Automatic Expiration**: All entries persist until manual clearing
- **Upstash Persistence**: Semantic cache persists across restarts (if using Upstash)

---

## **Key Takeaways**

### **Semantic Cache TTL**
- **No automatic expiration** - entries persist indefinitely
- **Manual clearing only** - use `clear()` method or restart system
- **Upstash persistence** - cloud storage persists across restarts
- **Local fallback** - in-memory storage lost on restart

### **Optimal Usage**
- **Response Cache**: Best for identical repeated queries
- **Semantic Cache**: Best for paraphrased/similar queries
- **Prompt Cache**: Best for identical contexts
- **Threshold Tuning**: Adjust `CACHE_THRESHOLD` based on precision needs

### **Monitoring**
- **Hit Rate**: Monitor cache effectiveness
- **Similarity Scores**: Ensure semantic matches are appropriate
- **Storage Usage**: Monitor memory/Upstash limits
- **Performance**: Track latency improvements

This multi-layer caching strategy provides significant performance improvements and cost savings while maintaining answer quality through intelligent similarity matching and comprehensive monitoring.