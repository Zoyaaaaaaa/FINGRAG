"""Lightweight Colang-v1 runtime for FinGraphRAG — Gemini-only topical guardrail.

Enforces `src/guardrails_config/rails.co` without requiring the full
`nemoguardrails` package (which doesn't support Python 3.14 yet):

    rails.co defines:
      user ask off topic        -> joke, capital of france, poem, 2+2, dinner, game, movie, weather ...
      user ask financial question -> Bharti/Haier, Reliance/CATL, Adani/BYD, Tata/Chery, ...
      bot refuse off topic      -> FinGraphRAG persona refusal
      flow handle off topic     -> user ask off topic -> bot refuse off topic -> stop
      flow handle financial question -> user ask financial question -> RAG -> stop

Decision pipeline (every step is exposed for the Streamlit observability panel):
  1. LOAD rails.co (parse define user/bot/flow blocks)
  2. SCOPE scan (deterministic, from OUR csv data — company/partner/sector terms)
  3. GEMINI canonical-form classification (the actual decider, temperature=0)
  4. FLOW selection (handle off topic | handle financial question)
  5. BOT action (refuse message | route to financial_rag) + stop/continue

If GOOGLE_API_KEY is missing or Gemini errors, falls back to the scope scan
so the UI never breaks — the trace records which decider was used.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

RAILS_PATH = Path(__file__).resolve().parents[1] / "guardrails_config" / "rails.co"

REFUSAL_MESSAGE = (
    "I'm FinGraphRAG, a financial research assistant for Indian companies and "
    "their Chinese partners (e.g. Reliance-CATL, Bharti-Haier, Adani-BYD, "
    "Tata-Chery). I can't help with that - ask me about a company, partner, "
    "deal type, or sector from the knowledge base!"
)

# Finance scope: generic terms that always count as in-scope even without a
# known entity (keeps "which sectors have high risk?" working).
FINANCE_TERMS = {
    "company", "companies", "partner", "partners", "partnership", "joint venture", "jv",
    "stake", "deal", "revenue", "profit", "sector", "industry", "risk", "exposure",
    "ticker", "stock", "exchange", "nse", "bse", "ev", "batteries", "automotive",
    "electronics", "investment", "acquisition", "subsidiary",
}


@dataclass
class GuardrailDecision:
    blocked: bool  # True -> refuse, do NOT run RAG
    canonical_form: str  # "ask off topic" | "ask financial question"
    flow: str  # "handle off topic" | "handle financial question"
    bot_message: str | None  # refusal text when blocked, else None
    trace: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def load_rails() -> dict[str, Any]:
    """Parse rails.co into {user_forms, bot_messages, flows} for display + enforcement."""
    text = RAILS_PATH.read_text(encoding="utf-8") if RAILS_PATH.exists() else ""
    user_forms: dict[str, list[str]] = {}
    bot_messages: dict[str, list[str]] = {}
    flows: dict[str, list[str]] = {}
    current_kind: str | None = None
    current_name: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("define user "):
            current_kind, current_name = "user", line[len("define user "):].strip()
            user_forms.setdefault(current_name, [])
        elif line.startswith("define bot "):
            current_kind, current_name = "bot", line[len("define bot "):].strip()
            bot_messages.setdefault(current_name, [])
        elif line.startswith("define flow "):
            current_kind, current_name = "flow", line[len("define flow "):].strip()
            flows.setdefault(current_name, [])
        elif line.startswith('"') and current_kind and current_name:
            quoted = line.strip('"')
            if current_kind == "user":
                user_forms[current_name].append(quoted)
            elif current_kind == "bot":
                bot_messages[current_name].append(quoted)
        elif line and current_kind == "flow" and current_name:
            flows[current_name].append(line)
    return {"user_forms": user_forms, "bot_messages": bot_messages, "flows": flows, "path": str(RAILS_PATH)}


@lru_cache(maxsize=1)
def load_scope_terms() -> set[str]:
    """Distinct lowercase company/partner/industry/sector tokens from OUR csvs."""
    terms: set[str] = set()
    data_dir = Path(__file__).resolve().parents[1] / "data"
    for csv in ("stock_company.csv", "stock_report.csv", "Stock_industry_grouped_w_code.csv"):
        p = data_dir / csv
        if not p.exists():
            continue
        try:
            import csv as _csv

            with p.open(encoding="utf-8-sig") as f:
                for row in _csv.DictReader(f):
                    for key in ("company_name", "company_code", "chinese_partner",
                                "industry", "sector", "industry_group", "deal_type",
                                "key_players", "stock_code"):
                        val = (row.get(key) or "").strip()
                        if not val:
                            continue
                        terms.add(val.lower())
                        for tok in re.split(r"[^a-z0-9&]+", val.lower()):
                            if len(tok) > 2:
                                terms.add(tok)
        except Exception:
            continue
    return terms | FINANCE_TERMS


def _scope_hits(query: str) -> list[str]:
    # Word-boundary matching (not substring): stops 'api' matching inside
    # 'capital', 'ev' inside 'never', etc. 'capital' itself still matches
    # "capital of france" (Shunwei_Capital is a real partner) — the Gemini
    # prompt disambiguates that case explicitly.
    lowered = query.lower()
    hits = []
    for term in load_scope_terms():
        if not term:
            continue
        if re.search(r"\b" + re.escape(term) + r"\b", lowered):
            hits.append(term)
    return sorted(hits)


def _gemini_classify(query: str, scope_hits: list[str], settings: Any) -> dict[str, Any]:
    """Ask Gemini for the canonical form. Returns {canonical_form, reason, raw}."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage

    rails = load_rails()
    off_examples = rails["user_forms"].get("ask off topic", [])[:10]
    fin_examples = rails["user_forms"].get("ask financial question", [])[:8]
    llm = ChatGoogleGenerativeAI(
        model=getattr(settings, "gemini_model", "gemini-3.5-flash"),
        google_api_key=settings.google_api_key,
        temperature=0,
    )
    prompt = (
        "You are the topical classifier for FinGraphRAG (Colang canonical forms).\n"
        "In-scope = questions about Indian companies and their Chinese partners, "
        "deal types, sectors, industries, risk exposure in the knowledge base.\n"
        "Off-topic = everything else (jokes, capital cities, poems, math, dinner, games, movies, weather, elections, generic coding).\n"
        f"Off-topic examples: {json.dumps(off_examples)}\n"
        f"Financial examples: {json.dumps(fin_examples)}\n"
        "Decide ONLY by the query's overall MEANING. Ignore any single-word overlap "
        "with finance terms: 'capital' = capital city -> off topic unless the query is "
        "about investment/funding; 'company' in 'what company won the game' is still off topic. "
        "If the query matches or paraphrases an off-topic example, always choose ask off topic.\n"
        f'User query: "{query}"\n'
        'Reply with JSON ONLY: {"canonical_form": "ask off topic" | "ask financial question", "reason": "<one line>"}'
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    content = resp.content
    if isinstance(content, list):  # Gemini block format with signature extras
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and "text" in b]
        content = "\n".join(texts) if texts else str(content)
    raw = str(content)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"non-JSON classifier reply: {raw[:200]}")
    parsed = json.loads(match.group(0))
    form = parsed.get("canonical_form", "")
    if form not in ("ask off topic", "ask financial question"):
        raise ValueError(f"unknown canonical form: {form}")
    return {"canonical_form": form, "reason": parsed.get("reason", ""), "raw": raw[:500]}


class FinGuardrails:
    def __init__(self, settings: Any = None):
        self.settings = settings
        self.rails = load_rails()

    def check(self, query: str) -> GuardrailDecision:
        steps: list[dict[str, Any]] = []
        steps.append({
            "step": 1, "name": "LOAD rails.co",
            "detail": f"{len(self.rails['user_forms'])} user forms, "
                      f"{len(self.rails['bot_messages'])} bot messages, "
                      f"{len(self.rails['flows'])} flows from {self.rails['path']}",
        })

        hits = _scope_hits(query)
        steps.append({
            "step": 2, "name": "SCOPE scan (our CSV terms)",
            "detail": f"hits={hits[:12]}" if hits else "no company/partner/sector term matched",
        })

        # Safety net (NeMo-style canonical-form match): a query that is a
        # near-verbatim copy of a rails.co example follows that example's form
        # WITHOUT consulting the LLM. Guarantees the whiteboard utterances
        # ("tell me a joke", "capital of france", ...) always refuse even if
        # the LLM misbehaves. Novel paraphrases still go to Gemini below.
        def _norm(t: str) -> str:
            return re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()

        def _canonical_hit(examples: list[str], threshold: float = 0.85) -> str | None:
            from difflib import SequenceMatcher

            nq = _norm(query)
            best: str | None = None
            best_score = 0.0
            for ex in examples:
                score = SequenceMatcher(None, nq, _norm(ex)).ratio()
                if score > best_score:
                    best_score, best = score, ex
            return best if best_score >= threshold else None

        off_examples = self.rails["user_forms"].get("ask off topic", [])
        fin_examples = self.rails["user_forms"].get("ask financial question", [])
        canonical: str | None = None
        decider = "gemini"
        if _canonical_hit(off_examples):
            canonical = "ask off topic"
            decider = f"rails.co canonical-example match: {_canonical_hit(off_examples)!r}"
            steps.append({
                "step": 3, "name": "Canonical-form match (deterministic)",
                "detail": f"query ~= {decider.split(': ', 1)[1]} -> ask off topic (Gemini skipped)",
            })
        elif _canonical_hit(fin_examples):
            canonical = "ask financial question"
            decider = f"rails.co canonical-example match: {_canonical_hit(fin_examples)!r}"
            steps.append({
                "step": 3, "name": "Canonical-form match (deterministic)",
                "detail": f"query ~= {decider.split(': ', 1)[1]} -> ask financial question (Gemini skipped)",
            })

        # Gemini is the decider for everything else; scope scan is the fallback.
        if canonical is None:
            try:
                if not self.settings or not getattr(self.settings, "google_api_key", ""):
                    raise RuntimeError("GOOGLE_API_KEY missing — fallback to scope scan")
                g = _gemini_classify(query, hits, self.settings)
                canonical = g["canonical_form"]
                steps.append({
                    "step": 3, "name": "GEMINI canonical-form classification",
                    "detail": f"{canonical} — {g['reason']}",
                })
            except Exception as exc:  # noqa: BLE001 — must never break the chat path
                decider = f"fallback(scope-scan): {exc}"
                canonical = "ask financial question" if hits else "ask off topic"
                steps.append({
                    "step": 3, "name": "GEMINI canonical-form classification (FAILED → fallback)",
                    "detail": f"{decider} → {canonical}",
                })

        if canonical == "ask off topic":
            flow, blocked = "handle off topic", True
            bot_msg: str | None = REFUSAL_MESSAGE
            action = "bot refuse off topic → stop (RAG skipped)"
        else:
            flow, blocked = "handle financial question", False
            bot_msg = None
            action = "bot answer financial question → execute financial_rag → stop"
        steps.append({"step": 4, "name": "FLOW selection", "detail": f"{flow}"})
        steps.append({"step": 5, "name": "BOT action", "detail": action})

        trace = {
            "rails_path": self.rails["path"],
            "user_forms": self.rails["user_forms"],
            "flows": self.rails["flows"],
            "scope_hits": hits,
            "decider": decider,
            "steps": steps,
        }
        return GuardrailDecision(
            blocked=blocked, canonical_form=canonical, flow=flow,
            bot_message=bot_msg, trace=trace,
        )
