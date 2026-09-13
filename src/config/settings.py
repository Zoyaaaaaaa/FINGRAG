from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parents[1]
for env_path in (project_root / ".env", project_root / "src" / ".env"):
    if env_path.exists():
        load_dotenv(env_path, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    google_api_key: str = Field(default="", validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"))
    gemini_model: str = Field(default="gemini-3-flash-preview", validation_alias=AliasChoices("GEMINI_MODEL", "GEMINI_MODEL_NAME"))
    embedding_model: str = Field(default="models/gemini-embedding-001", validation_alias="EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=3072, validation_alias="EMBEDDING_DIMENSIONS")

    qdrant_url: str = Field(default="", validation_alias="QDRANT_URL")
    qdrant_api_key: str = Field(default="", validation_alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="financial_documents", validation_alias="QDRANT_COLLECTION")

    neo4j_uri: str = Field(default="", validation_alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", validation_alias=AliasChoices("NEO4J_USER", "NEO4J_USERNAME"))
    neo4j_password: str = Field(default="", validation_alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", validation_alias="NEO4J_DATABASE")

    langsmith_api_key: str = Field(default="", validation_alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="fin-graph-rag", validation_alias="LANGSMITH_PROJECT")
    langsmith_tracing: bool = Field(default=True, validation_alias="LANGSMITH_TRACING")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com", validation_alias="LANGSMITH_ENDPOINT")

    langchain_api_key: str = Field(default="", validation_alias="LANGCHAIN_API_KEY")
    langchain_project: str = Field(default="fin-graph-rag", validation_alias="LANGCHAIN_PROJECT")
    langchain_tracing_v2: bool = Field(default=True, validation_alias="LANGCHAIN_TRACING_V2")

    memory_window_size: int = Field(default=10, validation_alias="MEMORY_WINDOW_SIZE")
    chunk_size: int = Field(default=1200, validation_alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=150, validation_alias="CHUNK_OVERLAP")

    # Upstash Semantic Cache (optional — falls back to local if not set)
    upstash_url: str = Field(default="", validation_alias="UPSTASH_VECTOR_REST_URL")
    upstash_token: str = Field(default="", validation_alias="UPSTASH_VECTOR_REST_TOKEN")
    cache_threshold: float = Field(default=0.88, validation_alias="CACHE_THRESHOLD")

    @property
    def effective_langsmith_api_key(self) -> str:
        return self.langchain_api_key or self.langsmith_api_key

    @property
    def effective_langsmith_project(self) -> str:
        return self.langchain_project or self.langsmith_project

    @property
    def effective_langsmith_tracing(self) -> bool:
        return self.langchain_tracing_v2 or self.langsmith_tracing


@lru_cache
def get_settings() -> Settings:
    return Settings()
