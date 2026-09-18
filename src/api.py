from fastapi import FastAPI, HTTPException

from src.config.settings import get_settings
from src.models.schemas import HealthResponse, QueryRequest, QueryResponse
from src.orchestrator import FinGraphRAG
from src.rails import RailsOrchestrator

app = FastAPI(title="FinGraphRAG", version="0.1.0")
system = FinGraphRAG(get_settings())
rails_orchestrator = RailsOrchestrator(get_settings())


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    services = system.health()
    services["rails"] = "enabled"
    status = "ok" if all(value in ("ok", "enabled") for value in services.values()) else "degraded"
    return HealthResponse(status=status, services=services)


@app.get("/rails/status")
def rails_status() -> dict[str, any]:
    """Get detailed status of all rails components."""
    return rails_orchestrator.get_rails_status()


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    try:
        # Execute input validation first
        input_result = rails_orchestrator.execute_input_rails_only(request.query)
        if not input_result.is_valid:
            raise HTTPException(
                status_code=400, 
                detail=f"Input validation failed: {input_result.reason}"
            )
        
        # Proceed with normal query flow (rails will be applied internally)
        result = system.query(input_result.sanitized_query, request.session_id, request.top_k)
        
        # Apply output rails
        output_result = rails_orchestrator.execute_output_rails_only(
            result["answer"],
            {"query": request.query, "sources": result.get("sources", [])}
        )
        
        if not output_result.is_valid:
            raise HTTPException(
                status_code=500,
                detail=f"Output validation failed: {output_result.reason}"
            )
        
        # Update result with sanitized response
        result["answer"] = output_result.sanitized_response
        result["rails_trace"] = {
            "input_validation": {
                "sanitized": input_result.sanitized_query != request.query,
                "reason": input_result.reason
            },
            "output_validation": {
                "quality_score": output_result.quality_score,
                "filtered_content": output_result.filtered_content
            }
        }
        
        return QueryResponse(**result)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.delete("/memory/{session_id}")
def clear_memory(session_id: str) -> dict[str, str]:
    system.memory.clear(session_id)
    return {"status": "cleared", "session_id": session_id}
