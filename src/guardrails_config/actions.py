"""NeMo Guardrails custom actions for FinGraphRAG.

When running under real NeMo (`nemoguardrails chat --config src/guardrails_config`),
the `execute financial_rag` step in rails.co calls `financial_rag` below,
which delegates to the same LangGraph pipeline the Streamlit app uses.
Our lightweight runtime (src/guardrails/fin_guardrails.py) calls the pipeline
directly and only uses this file as documentation / NeMo entrypoint.
"""

from typing import Any


async def financial_rag(context: dict[str, Any]) -> str:
    # Lazy import so `nemoguardrails actions-server` doesn't need DBs at import time.
    from src.config.settings import get_settings
    from src.orchestrator import FinGraphRAG

    settings = get_settings()
    system = FinGraphRAG(settings)
    last_user = ""
    for msg in reversed(context.get("history", [])):
        if msg.get("role") == "user":
            last_user = msg.get("content", "")
            break
    result = system.query(last_user or context.get("user_message", ""))
    return result["answer"]
