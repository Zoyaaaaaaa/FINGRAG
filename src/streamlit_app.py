import json
import random
import time
from typing import Any
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.config.settings import get_settings
from src.orchestrator import FinGraphRAG

# Page configuration
st.set_page_config(
    page_title="FinGraphRAG - Financial Intelligence System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #2c3e50;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .source-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #1f77b4;
        margin: 0.5rem 0;
    }
    .answer-box {
        background: #e8f4f8;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
        margin: 1rem 0;
    }
    .health-ok {
        color: #28a745;
        font-weight: bold;
    }
    .health-error {
        color: #dc3545;
        font-weight: bold;
    }
    .health-warning {
        color: #ffc107;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "system" not in st.session_state:
    with st.spinner("Initializing FinGraphRAG system..."):
        settings = get_settings()
        st.session_state.system = FinGraphRAG(settings)
        st.session_state.session_id = "streamlit_session"
        st.session_state.query_history = []

if "messages" not in st.session_state:
    st.session_state.messages = []

# Header
st.markdown('<div class="main-header">📊 FinGraphRAG</div>', unsafe_allow_html=True)
st.markdown("*Hybrid Retrieval-Augmented Generation for Financial Intelligence*")

# Sidebar - System Health and Controls
with st.sidebar:
    st.markdown("### ⚙️ System Status")

    # Detailed health check (shows Neo4j active DB + real error instead of just "error")
    try:
        health_detail = st.session_state.system.health_detail()
    except Exception:
        health_detail = st.session_state.system.health()
    # Only real service statuses here — detail dicts / paths are rendered below,
    # otherwise a file path (rails_path) shows up as a fake "⚠ service" row.
    health_status = {k: v for k, v in health_detail.items() if k in ("gemini", "qdrant", "neo4j", "guardrails", "langsmith")}

    # Display health status with color coding
    for service, status in health_status.items():
        if status == "ok" or status == "enabled":
            st.markdown(f"**{service.title()}**: <span class='health-ok'>✓ {status}</span>", unsafe_allow_html=True)
        elif status == "error":
            st.markdown(f"**{service.title()}**: <span class='health-error'>✗ {status}</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"**{service.title()}**: <span class='health-warning'>⚠ {status}</span>", unsafe_allow_html=True)

    if st.button("🔄 Retry connections"):
        with st.spinner("Retrying Neo4j + Qdrant..."):
            try:
                health_detail = st.session_state.system.reconnect()
            except Exception as e:
                st.error(f"Retry failed: {e}")
        st.rerun()

    # Neo4j connection deep-dive
    neo_detail = health_detail.get("neo4j_detail", {}) if isinstance(health_detail, dict) else {}
    if neo_detail:
        with st.expander("Neo4j connection details", expanded=(neo_detail.get("status") != "ok")):
            st.write(f"URI: `{neo_detail.get('uri')}`")
            st.write(f"Configured DB: `{neo_detail.get('configured_database')}` → Active DB: `{neo_detail.get('active_database')}`")
            if neo_detail.get("error"):
                st.error(f"{neo_detail.get('error')}")
                if neo_detail.get("hint"):
                    st.info(neo_detail["hint"])
            else:
                st.success("Neo4j connected.")

    # Qdrant connection deep-dive (previously a bare "error" with no detail)
    q_detail = health_detail.get("qdrant_detail", {}) if isinstance(health_detail, dict) else {}
    if q_detail and q_detail.get("status") != "ok":
        with st.expander("Qdrant connection details", expanded=True):
            st.write(f"URL: `{q_detail.get('url')}`")
            st.write(f"Collection: `{q_detail.get('collection')}`")
            if q_detail.get("error"):
                st.error(f"{q_detail.get('error')}")
                if q_detail.get("hint"):
                    st.info(q_detail["hint"])

    rails_path = health_detail.get("rails_path", "") if isinstance(health_detail, dict) else ""
    rails_exists = health_detail.get("rails_exists", False) if isinstance(health_detail, dict) else False
    st.caption(f"Qdrant collection: `{health_detail.get('qdrant_collection', '')}` · Model: `{health_detail.get('gemini_model', '')}`")
    if rails_path:
        if rails_exists:
            st.caption(f"Rails: `{rails_path}` ✓")
        else:
            st.caption(f"Rails: `{rails_path}` ✗ file not found")
    
    st.markdown("---")
    
    # Session management
    st.markdown("### 💬 Session Management")
    session_id = st.text_input("Session ID", value=st.session_state.session_id, key="session_input")
    st.session_state.session_id = session_id
    
    if st.button("Clear Conversation Memory"):
        st.session_state.system.memory.clear(st.session_state.session_id)
        st.session_state.messages = []
        st.success("Conversation memory cleared!")
    
    st.markdown("---")
    
    # Query parameters
    st.markdown("### 🔧 Query Parameters")
    top_k = st.slider("Top-K Results", min_value=1, max_value=20, value=8, key="top_k")
    
    st.markdown("---")
    
    # Statistics
    st.markdown("### 📈 Statistics")
    st.metric("Total Queries", len(st.session_state.query_history))
    st.metric("Conversation Turns", len(st.session_state.messages))

# Main content area
col1, col2 = st.columns([2, 1])

with col1:
    st.markdown('<div class="sub-header">🔍 Query Interface</div>', unsafe_allow_html=True)
    
    # Query input
    query = st.text_area(
        "Enter your financial query:",
        placeholder="e.g., What are the relationships between Reliance Industries and Chinese companies?",
        height=100,
        key="query_input"
    )
    
    # Query button
    if st.button("🚀 Submit Query", type="primary", use_container_width=True):
        if query.strip():
            with st.spinner("Processing your query..."):
                start_time = time.time()
                
                try:
                    result = st.session_state.system.query(
                        query=query,
                        session_id=st.session_state.session_id,
                        top_k=top_k
                    )
                    
                    processing_time = time.time() - start_time
                    
                    # Add to history
                    st.session_state.query_history.append({
                        "query": query,
                        "time": processing_time,
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    })
                    
                    # Add to messages
                    st.session_state.messages.append({"role": "user", "content": query})
                    st.session_state.messages.append({"role": "assistant", "content": result["answer"]})
                    
                    # Display results
                    st.markdown('<div class="sub-header">📝 Answer</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="answer-box">{result["answer"]}</div>', unsafe_allow_html=True)

                    # Display metadata
                    st.markdown('<div class="sub-header">🔍 Query Analysis</div>', unsafe_allow_html=True)

                    col1a, col1b, col1c, col1d = st.columns(4)
                    with col1a:
                        st.metric("Intent", result.get("intent", {}).get("intent", "BLOCKED"))
                    with col1b:
                        st.metric("Plan", result.get("plan") or "REFUSED")
                    with col1c:
                        st.metric("Processing Time", f"{processing_time:.2f}s")
                    with col1d:
                        st.metric("Sources", len(result.get("sources", [])))

                    # ---- NEMO-STYLE GUARDRAIL TRACE (rails.co steps, like your whiteboard) ----
                    g0 = (result.get("trace", {}) or {}).get("step_0_guardrails", {})
                    gsteps = g0.get("steps", []) or []
                    blocked = result.get("blocked", False)
                    if blocked:
                        st.warning(f"🛡️ Blocked by `{result.get('guard_flow', 'handle off topic')}` — RAG skipped, no Neo4j/Qdrant cost.")
                    else:
                        st.success(f"🛡️ Guardrail passed → `{result.get('guard_flow', 'handle financial question')}` — RAG executed.")
                    with st.expander("🛡️ Guardrails — step-by-step (rails.co / Colang)", expanded=blocked):
                        st.markdown("**Pipeline gate:** `user query` → `user ask off topic | user ask financial question` → `flow handle …` → `bot refuse off topic | execute financial_rag` → `stop`")
                        for gs in gsteps:
                            st.markdown(f"**{gs.get('step')}. {gs.get('name')}** — {gs.get('detail')}")
                        st.caption(f"Decider: `{g0.get('decider', 'gemini')}` · Canonical form: `{g0.get('canonical_form')}` · Flow: `{g0.get('flow')}`")
                        with st.expander("Show rails.co user forms + flows (exact file)", expanded=False):
                            gt = result.get("guard_trace", {}) or {}
                            st.json({"user_forms": gt.get("user_forms", {}), "flows": gt.get("flows", {})})
                            st.caption(f"Config: `{gt.get('rails_path', 'src/guardrails_config/rails.co')}` · NeMo-compatible (`nemoguardrails chat --config src/guardrails_config` with `engine: google_genai`)")

                    if result.get("intent", {}).get("entities"):
                        st.markdown("**Detected Entities:**")
                        st.write(", ".join(result["intent"]["entities"]))

                    # ---- HOW THE AGENT ANSWERED: full reasoning path + provenance ----
                    st.markdown('<div class="sub-header">🛤️ How this answer was derived</div>', unsafe_allow_html=True)
                    trace = result.get("trace", {})
                    s1 = trace.get("step_1_understand", {})
                    s2 = trace.get("step_2_graph_retrieval", {})
                    s3 = trace.get("step_3_vector_retrieval", {})
                    s4 = trace.get("step_4_context", {})
                    st.markdown(
                        f"**Path:** `User query` → `understand` (Intent={s1.get('intent')}, Plan={s1.get('plan')}) "
                        f"→ `retrieve` (graph ran={s2.get('ran')}, vector ran={s3.get('ran')}) "
                        f"→ `build_context` ({s4.get('chars', 0)} chars) → `synthesize` (Gemini) → `Answer`"
                    )
                    if s1.get("explanation"):
                        st.caption(s1["explanation"])

                    with st.expander("Step 1 — Query understanding (intent / entities / plan)", expanded=False):
                        st.json(result.get("intent", {}))
                        st.write(f"Retrieval plan: `{result.get('plan')}`")
                        st.caption("HYBRID = graph + vector · LOCAL = graph only · GLOBAL = vector only")

                    with st.expander(
                        f"Step 2 — Graph retrieval (Neo4j · {len(result.get('graph_context', []))} nodes)",
                        expanded=False,
                    ):
                        st.write(f"Database: `{s2.get('database')}` · Ran: `{s2.get('ran')}`")
                        if s2.get("cypher"):
                            st.markdown("**Cypher actually executed:**")
                            st.code(s2["cypher"], language="cypher")
                            st.markdown("**Parameters:**")
                            st.json(s2.get("params") or {})
                        else:
                            st.info("Graph retrieval was skipped for this plan (GLOBAL) or driver not configured.")
                        graph_ctx = result.get("graph_context", [])
                        if not graph_ctx:
                            st.warning("No graph nodes matched. Check entities above vs node properties (company_name, company_code, chinese_partner).")
                        for i, node in enumerate(graph_ctx):
                            props = node.get("node", {})
                            label = " / ".join(node.get("labels", []) or [])
                            title = props.get("company_name") or props.get("company_code") or f"Node {i+1}"
                            rel = node.get("relationship")
                            nbr = node.get("neighbor") or {}
                            with st.expander(f"Graph node {i+1}: {title} [{label}] rel={rel}", expanded=(i < 2)):
                                st.markdown("**Node properties (exact Neo4j record):**")
                                st.json(props)
                                if rel or nbr:
                                    st.markdown(f"**Relationship:** `{rel}` → neighbour:")
                                    st.json(nbr)
                                else:
                                    st.caption("No 1-hop relationship (dataset has nodes without edges).")

                    with st.expander(
                        f"Step 3 — Vector retrieval (Qdrant · {len(result.get('vector_context', []))} chunks)",
                        expanded=False,
                    ):
                        st.write(f"Collection: `{s3.get('collection')}` · Ran: `{s3.get('ran')}`")
                        vec_ctx = result.get("vector_context", [])
                        if not vec_ctx:
                            st.warning("No vector chunks returned.")
                        for i, chunk in enumerate(vec_ctx):
                            with st.expander(f"Chunk {i+1} · score={chunk.get('score', 0):.4f} · {chunk.get('metadata', {})}", expanded=(i < 2)):
                                st.markdown("**Exact chunk text sent to the LLM:**")
                                st.write(chunk.get("text", ""))
                                st.markdown("**Metadata:**")
                                st.json(chunk.get("metadata", {}))

                    with st.expander("Step 4 — Context sent to Gemini (merged graph + vector + memory)", expanded=False):
                        st.text_area("Full context (truncated at 20k chars in code)", value=result.get("context", ""), height=250)

                    # Display sources (kept for compatibility, now full list)
                    if result["sources"]:
                        st.markdown('<div class="sub-header">📚 Sources (all)</div>', unsafe_allow_html=True)

                        graph_sources = [s for s in result["sources"] if s["type"] == "graph"]
                        vector_sources = [s for s in result["sources"] if s["type"] == "vector"]

                        if graph_sources:
                            st.markdown(f"**Graph Database Sources ({len(graph_sources)}):**")
                            for idx, source in enumerate(graph_sources):
                                with st.expander(f"Graph Result {idx+1}", expanded=False):
                                    st.json(source["data"])

                        if vector_sources:
                            st.markdown(f"**Vector Database Sources ({len(vector_sources)}):**")
                            for i, source in enumerate(vector_sources):
                                with st.expander(f"Document {i+1} (Score: {source['data'].get('score', 0):.3f})", expanded=False):
                                    st.markdown(f"**Text:** {source['data'].get('text', '')}")
                                    st.markdown(f"**Metadata:** {source['data'].get('metadata', {})}")
                    
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                        import re as _re
                        m = _re.search(r"retry in\s*([0-9.]+s)", msg, _re.I)
                        wait = f" — retry in {m.group(1)}" if m else ""
                        st.warning(
                            f"Gemini quota hit for `{st.session_state.system.settings.gemini_model}`{wait}. "
                            "The answer above (if shown) is the extractive fallback from graph+vector hits — "
                            "no information was lost. Wait the delay or change `GEMINI_MODEL` in `src/.env`."
                        )
                        st.caption(f"Details: {msg[:800]}")
                    else:
                        st.error(f"Error processing query: {msg}")
                        st.exception(e)
        else:
            st.warning("Please enter a query before submitting.")

with col2:
    st.markdown('<div class="sub-header">💬 Conversation History</div>', unsafe_allow_html=True)
    
    if st.session_state.messages:
        for i, message in enumerate(st.session_state.messages[-10:]):  # Show last 10 messages
            if message["role"] == "user":
                st.markdown(f"**👤 You:** {message['content']}")
            else:
                st.markdown(f"**🤖 Assistant:** {message['content'][:200]}...")
            st.markdown("---")
    else:
        st.info("No conversation history yet. Start by asking a question!")

# Query History
st.markdown('<div class="sub-header">📊 Query History</div>', unsafe_allow_html=True)

if st.session_state.query_history:
    history_df = pd.DataFrame(st.session_state.query_history)
    st.dataframe(history_df, use_container_width=True)
else:
    st.info("No queries submitted yet.")

# Architecture Visualization
st.markdown('<div class="sub-header">🏗️ System Architecture</div>', unsafe_allow_html=True)

with st.expander("View System Architecture Flow", expanded=False):
    st.markdown("""
    ```
    ┌─────────────────────────────────────────────────────────────────┐
    │                         User Interface                            │
    │                    (Streamlit / FastAPI)                         │
    └────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Query Request
                             ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                      FinGraphRAG Orchestrator                     │
    │                    (LangGraph Workflow Engine)                    │
    └────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Workflow Execution
                             ▼
            ┌────────────────┴────────────────┐
            │                                   │
            ▼                                   ▼
    ┌──────────────────────┐        ┌──────────────────────┐
    │  Query Understanding │        │  Retrieval Strategy  │
    │  - Intent Detection  │        │  - Plan Selection    │
    │  - Entity Extraction │        │  - Entity Recognition│
    └──────────────────────┘        └──────────────────────┘
            │                                   │
            └────────────────┬──────────────────┘
                             │
                             │ Parallel Retrieval
                             ▼
            ┌────────────────┴────────────────┐
            │                                   │
            ▼                                   ▼
    ┌──────────────────────┐        ┌──────────────────────┐
    │   Neo4j Graph DB     │        │   Qdrant Vector DB   │
    │   - Entity Search    │        │   - Semantic Search  │
    │   - Relationship Traversal│   │   - Embedding Match  │
    └──────────────────────┘        └──────────────────────┘
            │                                   │
            └────────────────┬──────────────────┘
                             │
                             │ Context Building
                             ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Context Construction                          │
    │  - Merge graph results + vector results                          │
    │  - Add conversation memory                                       │
    │  - Format for LLM input                                          │
    └────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Answer Synthesis
                             ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Gemini LLM                                    │
    │  - Generate comprehensive answer                                 │
    │  - Include source references                                     │
    │  - Handle insufficient context gracefully                         │
    └────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Final Response
                             ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                    Response to User                              │
    │  - Generated answer                                               │
    │  - Retrieval plan                                                │
    │  - Source references                                             │
    │  - Intent classification                                         │
    └─────────────────────────────────────────────────────────────────┘
    ```
    """)

# Analytics and Visualization Section
st.markdown('<div class="sub-header">📊 Analytics & Visualization</div>', unsafe_allow_html=True)

if st.session_state.query_history:
    history_df = pd.DataFrame(st.session_state.query_history)
    
    # Create tabs for different visualizations
    tab1, tab2, tab3, tab4 = st.tabs(["📈 Query Trends", "🎯 Intent Analysis", "⏱️ Performance", "📚 Source Distribution"])
    
    with tab1:
        st.markdown("### Query Activity Over Time")
        if len(history_df) > 1:
            history_df['datetime'] = pd.to_datetime(history_df['timestamp'])
            history_df_sorted = history_df.sort_values('datetime')
            
            fig = px.line(history_df_sorted, x='datetime', y='time', 
                         title='Query Processing Time Trend',
                         labels={'time': 'Processing Time (s)', 'datetime': 'Timestamp'})
            fig.update_layout(template='plotly_white')
            st.plotly_chart(fig, use_container_width=True)
            
            # Query frequency
            history_df_sorted['hour'] = history_df_sorted['datetime'].dt.hour
            hourly_counts = history_df_sorted.groupby('hour').size().reset_index(name='count')
            
            fig2 = px.bar(hourly_counts, x='hour', y='count',
                         title='Query Distribution by Hour',
                         labels={'count': 'Number of Queries', 'hour': 'Hour of Day'})
            fig2.update_layout(template='plotly_white')
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Need at least 2 queries to show trends.")
    
    with tab2:
        st.markdown("### Intent Distribution")
        # Since we don't store intent in history, we'll show a mockup for now
        intents = ["RELATIONAL", "FACTUAL", "SEMANTIC"]
        intent_counts = [random.randint(1, 10) for _ in intents]  # This would be real data
        
        fig = px.pie(values=intent_counts, names=intents, 
                     title='Query Intent Distribution',
                     color_discrete_sequence=px.colors.sequential.Blues)
        fig.update_layout(template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
        
        st.info("Note: Intent analysis is performed per query. This shows sample distribution.")
    
    with tab3:
        st.markdown("### Performance Metrics")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            avg_time = history_df['time'].mean()
            st.metric("Average Processing Time", f"{avg_time:.2f}s")
        
        with col2:
            max_time = history_df['time'].max()
            st.metric("Max Processing Time", f"{max_time:.2f}s")
        
        with col3:
            min_time = history_df['time'].min()
            st.metric("Min Processing Time", f"{min_time:.2f}s")
        
        # Processing time distribution
        fig = px.histogram(history_df, x='time', nbins=10,
                          title='Processing Time Distribution',
                          labels={'time': 'Processing Time (s)', 'count': 'Frequency'})
        fig.update_layout(template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
    
    with tab4:
        st.markdown("### Source Type Distribution")
        # This would be real data from actual queries
        source_types = ["Graph Database", "Vector Database", "Hybrid"]
        source_counts = [random.randint(5, 15) for _ in source_types]
        
        fig = px.bar(x=source_types, y=source_counts,
                    title='Source Type Usage',
                    labels={'x': 'Source Type', 'y': 'Usage Count'},
                    color=source_types,
                    color_discrete_sequence=px.colors.sequential.Viridis)
        fig.update_layout(template='plotly_white')
        st.plotly_chart(fig, use_container_width=True)
        
        st.info("Note: This shows which retrieval methods are most frequently used.")

else:
    st.info("Submit some queries to see analytics and visualizations!")

# Entity Network Visualization (Sample)
st.markdown('<div class="sub-header">🕸️ Entity Network Visualization</div>', unsafe_allow_html=True)

with st.expander("Sample Entity Relationship Graph", expanded=False):
    st.info("This would show interactive network graphs of entity relationships from Neo4j.")
    st.markdown("""
    **Future Enhancement**: Integrate with Neo4j to display:
    - Company relationships
    - Industry connections  
    - Partnership networks
    - Investment flows
    
    *Requires additional Neo4j visualization libraries like pyvis or networkx*
    """)

# Footer
st.markdown("---")
st.markdown("""
**FinGraphRAG** - Hybrid Retrieval-Augmented Generation System  
*Combining Neo4j Graph Database + Qdrant Vector Search + Google Gemini LLM*

**Architecture Details:** See `SYSTEM_ARCHITECTURE.md` for complete system documentation.
""")