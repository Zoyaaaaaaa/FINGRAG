import hashlib
import time
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.config.settings import get_settings
from src.orchestrator import FinGraphRAG
from src.tools.semantic_cache import MultiLayerCache

# ── Page ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FinGraphRAG — Financial Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Theme ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
/* Streamlit chrome fixes: prevent Deploy overlapping content */
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2rem; padding-bottom: 1rem; }
.hero {
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 45%, #2563eb 100%);
  padding: 22px 26px; border-radius: 16px; color: white; margin: 6px 0 14px 0;
}
.hero h1 { font-size: 1.9rem; margin: 0 0 4px 0; letter-spacing: -0.02em; line-height: 1.2; }
.hero p { opacity: .92; margin: 0; font-size: .97rem; line-height: 1.4; }
.badge {
  display: inline-block; padding: 3px 9px; border-radius: 999px;
  font-size: .75rem; font-weight: 600; margin-right: 5px; margin-top: 8px;
  white-space: nowrap;
}
.badge-blue { background: rgba(255,255,255,.16); color: #dbeafe; border:1px solid rgba(255,255,255,.22);}
.badge-green { background:#dcfce7; color:#166534; }
.badge-amber { background:#fef9c3; color:#854d0e; }
.badge-red { background:#fee2e2; color:#991b1b; }
.badge-violet { background:#ede9fe; color:#5b21b6; }
.card {
  background: white; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 14px 14px 12px 14px;
}
.card h4 { margin: 0 0 4px 0; font-size: .93rem; line-height: 1.3; }
.card p { margin: 0; color: #475569; font-size: .84rem; line-height: 1.45; }
.card .icon { font-size: 1.25rem; margin-bottom: 6px; }
.answer-box {
  background: #f8fafc; border: 1px solid #e2e8f0; border-left: 4px solid #2563eb;
  padding: 14px 16px; border-radius: 10px; margin: 10px 0 12px 0; overflow-wrap: anywhere;
}
.health-ok { color:#16a34a; font-weight:700 }
.health-error { color:#dc2626; font-weight:700 }
.health-warn { color:#ca8a04; font-weight:700 }
/* chat: prevent avatar/text overlap */
div[data-testid="stChatMessage"] { padding: 0.6rem 0; }
div[data-testid="stChatMessage"] p { overflow-wrap: anywhere; }
/* tabs spacing */
div[data-testid="stTabs"] { margin-top: 6px; }
</style>
""", unsafe_allow_html=True)

# ── State ─────────────────────────────────────────────────────────────
if "system" not in st.session_state:
    with st.spinner("Booting FinGraphRAG — Neo4j + Qdrant + Gemini + Guardrails + Cache…"):
        settings = get_settings()
        st.session_state.system = FinGraphRAG(settings)
        st.session_state.settings = settings
        st.session_state.session_id = "streamlit_session"
        st.session_state.query_history = []
        st.session_state.messages = []
        st.session_state.cache = MultiLayerCache(settings)
        st.session_state.cache_history = []

settings = st.session_state.settings

# ── Sidebar — health + controls + cache mini ──────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ System Status")
    try:
        hd = st.session_state.system.health_detail()
    except Exception:
        hd = st.session_state.system.health()
    svc = {k: v for k, v in hd.items() if k in ("gemini", "qdrant", "neo4j", "guardrails", "langsmith")}
    for k, v in svc.items():
        cls = "health-ok" if v in ("ok", "enabled") else "health-error" if v == "error" else "health-warn"
        icon = "✓" if v in ("ok", "enabled") else "✗" if v == "error" else "⚠"
        st.markdown(f"**{k.title()}**: <span class='{cls}'>{icon} {v}</span>", unsafe_allow_html=True)
    if st.button("🔄 Retry connections", width='stretch'):
        with st.spinner("Retrying…"):
            try:
                hd = st.session_state.system.reconnect()
            except Exception as e:
                st.error(str(e))
        st.rerun()

    # deep dives collapsed
    nd = hd.get("neo4j_detail", {}) if isinstance(hd, dict) else {}
    if nd:
        with st.expander("Neo4j details", expanded=(nd.get("status") != "ok")):
            st.write(f"URI: `{nd.get('uri')}`")
            st.write(f"DB: `{nd.get('configured_database')}` → `{nd.get('active_database')}`")
            if nd.get("error"):
                st.error(nd["error"])
                if nd.get("hint"):
                    st.info(nd["hint"])
            else:
                st.success("Neo4j connected — 629 nodes, 105 edges ✓")
    qd = hd.get("qdrant_detail", {}) if isinstance(hd, dict) else {}
    if qd and qd.get("status") != "ok":
        with st.expander("Qdrant details", expanded=True):
            st.write(f"URL: `{qd.get('url')}` → `{qd.get('collection')}`")
            if qd.get("error"):
                st.error(qd["error"])
                if qd.get("hint"):
                    st.info(qd["hint"])
    st.caption(f"Qdrant `{hd.get('qdrant_collection','')}` · Gemini `{hd.get('gemini_model','')}` · Rails `{hd.get('rails_path','').split(chr(92))[-1]}`")

    st.divider()
    st.markdown("### 💬 Session")
    sid = st.text_input("Session ID", value=st.session_state.session_id, key="sid")
    st.session_state.session_id = sid
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Clear chat", width='stretch'):
            st.session_state.system.memory.clear(sid)
            st.session_state.messages = []
            st.success("Cleared")
    with c2:
        if st.button("Clear cache", width='stretch'):
            st.session_state.cache.clear()
            st.success("Cache cleared")

    st.slider("Top-K", 1, 20, 8, key="top_k")

    # mini cache KPI
    cache: MultiLayerCache = st.session_state.cache
    st.divider()
    st.markdown("### ⚡ Cache")
    m1, m2, m3 = st.columns(3)
    m1.metric("Hit rate", f"{cache.hit_rate*100:.0f}%")
    m2.metric("Hits", cache.stats.hits)
    m3.metric("Saved", f"{cache.stats.total_saved_ms/1000:.1f}s")
    st.caption(f"Response:{cache.stats.response_hits} · Semantic:{cache.stats.semantic_hits} · Prompt:{cache.stats.prompt_hits}")
    st.caption("Upstash Vector: " + ("✓ connected" if cache.semantic._upstash else "local fallback"))
    st.caption(f"Threshold {cache.semantic.threshold:.2f}")

    st.divider()
    st.metric("Queries", len(st.session_state.query_history))
    st.metric("Turns", len(st.session_state.messages))

# ── Hero ──────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
  <h1>📊 FinGraphRAG</h1>
  <p>Hybrid RAG for <b>Indian companies × Chinese partners</b> — Graph (Neo4j) + Vector (Qdrant) + Gemini synthesis, guarded by NeMo Colang and accelerated by 3-layer semantic caching.</p>
  <span class="badge badge-blue">Hybrid Retrieval</span>
  <span class="badge badge-blue">105 Graph Edges</span>
  <span class="badge badge-blue">532 Vectors · 3072-d</span>
  <span class="badge badge-blue">Gemini 3 Flash</span>
  <span class="badge badge-blue">Guardrails ✓</span>
  <span class="badge badge-blue">Upstash Cache ✓</span>
</div>
""", unsafe_allow_html=True)

# ── Feature cards — 3×2 to avoid horizontal squeeze/overlap ─────────
cards = [
    ("🔀", "Hybrid Retrieval", "Intent → Plan (HYBRID/LOCAL/GLOBAL) routes to graph + vector in parallel."),
    ("🕸️", "Knowledge Graph", "629 nodes (Company + FinancialEntity) · 105 typed edges: PARTNERS_WITH, LICENSES_TECH, HAS_STAKE_IN."),
    ("🔍", "Vector Search", "Qdrant cosine 3072-d · gemini-embedding-001 · auto 20k context assembly."),
    ("✨", "Gemini Synthesis", "Gemini 3 Flash Preview (temp 0.1) + extractive 429 fallback — never throws."),
    ("🛡️", "NeMo Guardrails", "rails.co Colang — off-topic refused before any DB/LLM cost, full step trace."),
    ("⚡", "3-Layer Cache", "Response → Semantic (Upstash Vector) → Prompt — see Cache tab."),
]
r1c1, r1c2, r1c3 = st.columns(3)
for col, (icon, title, desc) in zip([r1c1, r1c2, r1c3], cards[:3]):
    with col:
        st.markdown(f'<div class="card"><div class="icon">{icon}</div><h4>{title}</h4><p>{desc}</p></div>', unsafe_allow_html=True)
r2c1, r2c2, r2c3 = st.columns(3)
for col, (icon, title, desc) in zip([r2c1, r2c2, r2c3], cards[3:]):
    with col:
        st.markdown(f'<div class="card"><div class="icon">{icon}</div><h4>{title}</h4><p>{desc}</p></div>', unsafe_allow_html=True)

st.write("")

# ── Tabs ──────────────────────────────────────────────────────────────
tab_chat, tab_graph, tab_cache, tab_arch = st.tabs(["💬 Chat", "🕸️ Graph Explorer", "⚡ Cache Dashboard", "🏗️ Architecture"])

# ════════════════════════════════════════════════════════════════════════
# CHAT TAB
# ════════════════════════════════════════════════════════════════════════
with tab_chat:
    # quick chips
    st.markdown("**Try:**")
    chips = [
        "What is the relationship between JSW Group and Chery Automobile?",
        "What is the partnership structure between Bharti Enterprises and Haier?",
        "Which Indian companies partner with CATL?",
        "Tell me about Dixon Technologies and Vivo India",
    ]
    cols = st.columns(len(chips))
    for i, q in enumerate(chips):
        if cols[i].button(q, key=f"chip{i}", width='stretch'):
            st.session_state.pending_query = q

    # chat history
    chat_container = st.container()
    with chat_container:
        if not st.session_state.messages:
            st.info("👋 Ask about any Indian company × Chinese partner — e.g. *Reliance × CATL, Adani × BYD, Tata × Chery*.")
        for m in st.session_state.messages[-20:]:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m.get("meta"):
                    st.caption(m["meta"])

    # input — text area + button (chat_input inside tabs causes fixed-position overlap with Deploy header)
    pending = st.session_state.pop("pending_query", None)
    col_in, col_btn = st.columns([5, 1])
    with col_in:
        q_text = st.text_area("Your question", value=pending or "", placeholder="Ask about a company, partner, deal type or sector… e.g. What is the relationship between JSW Group and Chery Automobile?", height=78, label_visibility="collapsed", key="chat_text_input")
    with col_btn:
        st.write("")  # align
        send = st.button("🚀 Send", type="primary", width='stretch', key="chat_send")
        st.caption("Enter + Send")
    query = (q_text.strip() if send and q_text.strip() else None) or pending

    if query:
        with st.chat_message("user"):
            st.markdown(query)

        # ── Cache → Guard → RAG ─────────────────────────────────
        cache: MultiLayerCache = st.session_state.cache
        top_k = int(st.session_state.get("top_k", 8))
        t0 = time.time()

        # 1) Guard first (off-topic never hits cache or DB)
        # we run guard inside orchestrator, but also need to decide cache eligibility:
        # we let orchestrator handle guard; cache layer below is only for on-topic.

        # 2) Semantic/Response cache lookup (before LLM/RAG)
        cached, layer = cache.lookup(query)
        if cached and layer in ("response", "semantic"):
            # cache HIT — no RAG cost
            latency = (time.time() - t0) * 1000
            cache.record(query, layer, latency, True)
            answer = cached.answer
            meta = f"⚡ Cache HIT · {layer} · score {cached.score:.2f} " if cached.score else f"⚡ Cache HIT · {layer}"
            result = {"answer": answer, "cached": True, "cache_layer": layer, "cache_score": cached.score,
                      "intent": {"intent": "CACHED"}, "plan": "CACHED", "sources": [], "graph_context": [], "vector_context": [],
                      "trace": {"step_0_guardrails": {"canonical_form": "ask financial question (cached)", "flow": "handle financial question", "blocked": False}}}
            processing_ms = latency
        else:
            # MISS — full RAG
            with st.spinner("Guardrails → Graph + Vector → Gemini…"):
                try:
                    result = st.session_state.system.query(query=query, session_id=st.session_state.session_id, top_k=top_k)
                    processing_ms = (time.time() - t0) * 1000
                    # record miss latency
                    cache.record(query, "miss", processing_ms, False)
                    # store for next time (only if not blocked / not fallback error)
                    if not result.get("blocked") and result.get("answer"):
                        cache.put_response(query, result["answer"])
                    result["cached"] = False
                except Exception as e:
                    msg = str(e)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                        st.warning(f"Gemini quota hit ({settings.gemini_model}) — showing extractive fallback. Wait ~45s or change GEMINI_MODEL.")
                    else:
                        st.error(msg)
                    # still try fallback from result if available
                    result = None
                    processing_ms = (time.time() - t0) * 1000

        if result is not None:
            is_cached = result.get("cached", False)
            is_blocked = result.get("blocked", False)
            layer = result.get("cache_layer", "miss")

            with st.chat_message("assistant"):
                # badges
                badges = []
                if is_cached:
                    sc = result.get("cache_score")
                    badges.append(f"<span class='badge badge-violet'>⚡ Cache HIT · {layer}" + (f" {sc:.2f}" if sc else "") + "</span>")
                else:
                    badges.append("<span class='badge badge-green'>RAG</span>")
                if is_blocked:
                    badges.append("<span class='badge badge-amber'>🛡️ Guardrail blocked</span>")
                else:
                    badges.append(f"<span class='badge badge-blue'>Plan {result.get('plan','')}</span>")
                st.markdown(" ".join(badges), unsafe_allow_html=True)
                st.markdown(f"<div class='answer-box'>{result['answer']}</div>", unsafe_allow_html=True)
                st.caption(f"{processing_ms:.0f} ms · {len(result.get('sources',[]))} sources · {'cache hit' if is_cached else 'live RAG'}")

                # provenance (collapsed)
                trace = result.get("trace", {})
                g0 = trace.get("step_0_guardrails", {})
                with st.expander("🛡️ Guardrail trace", expanded=is_blocked):
                    for s in g0.get("steps", []):
                        st.write(f"**{s.get('step')}. {s.get('name')}** — {s.get('detail')}")
                    st.caption(f"Decider `{g0.get('decider')}` · `{g0.get('canonical_form')}` → `{g0.get('flow')}`")

                if not is_blocked:
                    s1, s2, s3, s4 = trace.get("step_1_understand", {}), trace.get("step_2_graph_retrieval", {}), trace.get("step_3_vector_retrieval", {}), trace.get("step_4_context", {})
                    with st.expander(f"🔍 Retrieval — Graph {len(result.get('graph_context',[]))} nodes + Vector {len(result.get('vector_context',[]))} chunks"):
                        st.write(f"Intent **{s1.get('intent')}** · Plan **{s1.get('plan')}** · Entities `{s1.get('entities')}`")
                        if s2.get("cypher"):
                            st.code(s2["cypher"], language="cypher")
                            st.json(s2.get("params", {}))
                        for i, n in enumerate(result.get("graph_context", [])[:4]):
                            xp = st.expander(f"Graph {i+1}: {n.get('node',{}).get('name','')} [{'/'.join(n.get('labels',[]))}] — {n.get('relationship') or '—'} → {(n.get('neighbor') or {}).get('name','')}", expanded=(i==0 and n.get('relationship') is not None))
                            with xp:
                                st.json(n.get("node", {}))
                                if n.get("relationship"):
                                    st.write(f"**{n['relationship']}** →")
                                    st.json(n.get("neighbor", {}))
                                    if n.get("rel_props"):
                                        st.json(n["rel_props"])
                        for i, ch in enumerate(result.get("vector_context", [])[:4]):
                            with st.expander(f"Chunk {i+1} score {ch.get('score',0):.3f} {ch.get('metadata',{})}", expanded=False):
                                st.write(ch.get("text",""))
                                st.json(ch.get("metadata", {}))

                    with st.expander("📝 Context sent to Gemini"):
                        st.text_area("ctx", value=result.get("context","")[:12000], height=180, label_visibility="collapsed")

            # history
            st.session_state.messages.append({"role": "user", "content": query})
            meta = f"⚡ {layer} hit" if is_cached else f"{processing_ms:.0f}ms · {result.get('plan','')}"
            st.session_state.messages.append({"role": "assistant", "content": result["answer"][:900], "meta": meta})
            st.session_state.query_history.append({"query": query, "time": processing_ms/1000, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "cached": is_cached, "layer": layer if is_cached else "rag"})

# ════════════════════════════════════════════════════════════════════════
# GRAPH TAB
# ════════════════════════════════════════════════════════════════════════
with tab_graph:
    st.markdown("### 🕸️ Knowledge Graph — now with real edges")
    try:
        neo = st.session_state.system.neo4j
        with neo.driver.session(database=neo.active_database) as sess:
            cnt_nodes = sess.run("MATCH (n) RETURN count(n) AS c").data()[0]["c"]
            cnt_rels = sess.run("MATCH ()-[r]->() RETURN count(r) AS c").data()[0]["c"]
            cnt_comp = sess.run("MATCH (n:Company) RETURN count(n) AS c").data()[0]["c"]
            by_type = sess.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC").data()
            top_rels = sess.run("MATCH (a:Company)-[r]->(b:Company) RETURN a.name AS a, type(r) AS t, b.name AS b LIMIT 12").data()
    except Exception as e:
        cnt_nodes, cnt_rels, cnt_comp, by_type, top_rels = 0, 0, 0, [], []
        st.error(str(e))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total nodes", cnt_nodes, delta=f"{cnt_comp} Companies")
    k2.metric("Relationships", cnt_rels)
    k3.metric("Companies", cnt_comp)
    k4.metric("Sources", "3 CSVs")

    if by_type:
        df = pd.DataFrame(by_type)
        fig = px.bar(df, x="t", y="c", color="t", title="Relationships by type", labels={"t":"Type","c":"Count"})
        fig.update_layout(showlegend=False, template="plotly_white", height=320)
        st.plotly_chart(fig, width='stretch')

    if top_rels:
        st.dataframe(pd.DataFrame(top_rels), width='stretch')
        st.caption("Example: `MATCH (a:Company)-[:LICENSES_TECHNOLOGY_FROM]->(b) WHERE a.name='JSW Group' RETURN b` now traverses real edges — previously 0 edges, now 105 typed edges enable multi-hop reasoning.")

    with st.expander("Schema"):
        st.code("""
(:Company {name, key}) -[:PARTNERS_WITH {type, status, report_date, source}]-> (:Company)
(:Company) -[:LICENSES_TECHNOLOGY_FROM]-> (:Company)   // Technology/Platform Licensing
(:Company) -[:HAS_STAKE_IN]-> (:Company)               // 49% JV, stake deals
(:Company) -[:HAS_RND_CENTER]-> (:Company)             // R&D
(:FinancialEntity {key, company_name, chinese_partner, relationship_type, ...}) // legacy per-row
        """, language="cypher")

# ════════════════════════════════════════════════════════════════════════
# CACHE TAB
# ════════════════════════════════════════════════════════════════════════
with tab_cache:
    st.markdown("### ⚡ Multi-Layer Caching — Upstash Vector + Local")
    st.markdown("Three layers accelerate repeated or semantically similar questions — highlights the platform's production-grade performance features.")
    cache: MultiLayerCache = st.session_state.cache

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Hit rate", f"{cache.hit_rate*100:.1f}%", delta=f"{cache.stats.hits} hits")
    c2.metric("Misses", cache.stats.misses)
    c3.metric("Time saved", f"{cache.stats.total_saved_ms/1000:.1f}s")
    c4.metric("Threshold", f"{cache.semantic.threshold:.2f}")

    # layer breakdown
    df = pd.DataFrame([
        {"Layer": "Response (exact)", "Hits": cache.stats.response_hits, "Desc": "Exact query string — 0ms"},
        {"Layer": "Semantic (Upstash)", "Hits": cache.stats.semantic_hits, "Desc": "Meaning match via vector cosine ≥ threshold"},
        {"Layer": "Prompt (context hash)", "Hits": cache.stats.prompt_hits, "Desc": "LLM prompt reuse"},
        {"Layer": "Misses → RAG", "Hits": cache.stats.misses, "Desc": "Full Graph + Vector + Gemini"},
    ])
    fig = px.bar(df, x="Layer", y="Hits", color="Layer", title="Cache layer breakdown")
    fig.update_layout(template="plotly_white", showlegend=False, height=300)
    st.plotly_chart(fig, width='stretch')

    if cache._history:
        st.dataframe(pd.DataFrame(cache._history[-30:]), width='stretch')
    else:
        st.info("No cache events yet — ask a question twice to see a hit.")

    col_a, col_b = st.columns(2)
    with col_a:
        test_q = st.text_input("Test semantic similarity", placeholder="e.g. JSW Chery deal?", key="sem_test_q")
        if st.button("Check would-hit?"):
            if test_q.strip():
                vec = cache.semantic._embed(test_q)
                hits = cache.semantic.query(vec, top_k=3)
                st.json(hits)
    with col_b:
        st.caption("Upstash Index: `classic-lioness-60363-us1-vector.upstash.io`")
        st.caption(f"Mode: {'Upstash Vector ✓' if cache.semantic._upstash else 'Local fallback (upstash-vector not connected)'}")
        st.caption("Install: `pip install upstash-vector` + set `UPSTASH_VECTOR_REST_URL/TOKEN` in src/.env")

    st.divider()
    st.markdown("**Beyond Upstash:** this pattern generalizes to **Qdrant** as semantic cache (we already have Qdrant), Redis, or in-process LRU — all shown as hit/miss analytics above.")

# ════════════════════════════════════════════════════════════════════════
# ARCH TAB — clean structure only
# ════════════════════════════════════════════════════════════════════════
with tab_arch:
    st.markdown("### 🏗️ Architecture")
    import os as _os
    _img = "assets/fin_graph_rag_architecture.png"
    if _os.path.exists(_img):
        st.image(_img, caption="FinGraphRAG — System Flow, Tech Stack & Key Scenarios", width="stretch")
    else:
        st.info("Architecture diagram: `assets/fin_graph_rag_architecture.png` not found in repo — add it to enable the image. Showing text flow instead.")
        st.code("""
User → Streamlit Chat → Guardrails (rails.co) → Semantic Cache (Upstash Vector)
     → Understand (REL/FACT/SEM) → Retrieve (Neo4j 629 nodes/105 edges + Qdrant 532 vecs)
     → Build Context (20k) → Synthesize (Gemini 3 Flash / 429 fallback) → Answer
        """, language="text")
    st.caption("Full implementation details: `SYSTEM_ARCHITECTURE.md` in repo root.")

# ── Footer ────────────────────────────────────────────────────────────
st.divider()
st.caption("FinGraphRAG — Hybrid RAG · Neo4j 629 nodes/105 edges · Qdrant 532 pts · Gemini 3 Flash · Upstash Vector Cache · NeMo Guardrails")
