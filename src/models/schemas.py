from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    session_id: str = "default"
    top_k: int = Field(default=8, ge=1, le=30)


class QueryResponse(BaseModel):
    answer: str
    plan: str = ""
    intent: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str
    blocked: bool = False
    guard_canonical: str | None = None
    guard_flow: str | None = None
    guard_trace: dict[str, Any] = Field(default_factory=dict)
    # Full provenance (optional so old clients keep working)
    graph_context: list[dict[str, Any]] = Field(default_factory=list)
    vector_context: list[dict[str, Any]] = Field(default_factory=list)
    context: str = ""
    trace: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    services: dict[str, str]
