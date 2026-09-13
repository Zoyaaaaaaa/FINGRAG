from fastapi import FastAPI, HTTPException

from src.config.settings import get_settings
from src.models.schemas import HealthResponse, QueryRequest, QueryResponse
from src.orchestrator import FinGraphRAG

app = FastAPI(title="FinGraphRAG", version="0.1.0")
system = FinGraphRAG(get_settings())


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    services = system.health()
    status = "ok" if all(value in ("ok", "enabled") for value in services.values()) else "degraded"
    return HealthResponse(status=status, services=services)


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    try:
        return QueryResponse(**system.query(request.query, request.session_id, request.top_k))
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.delete("/memory/{session_id}")
def clear_memory(session_id: str) -> dict[str, str]:
    system.memory.clear(session_id)
    return {"status": "cleared", "session_id": session_id}
