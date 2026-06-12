import os
from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Azure OpenAI — LLM
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_deployment: str  # e.g. "gpt-4o"
    azure_openai_api_version: str = "2024-02-01"

    # Azure OpenAI — Embeddings
    azure_embedding_deployment: str  # e.g. "text-embedding-3-small"
    # HuggingFace local embeddings
    hf_embedding_model: str = "BAAI/bge-small-en-v1.5"

    # LangSmith observability
    langsmith_tracing: bool = True
    langsmith_api_key: str = ""
    langsmith_project: str = "default"

    # Qdrant vector store
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    qdrant_collection: str = "incident_memory"

    # Checkpoint store
    checkpoint_backend: str = "memory"  # "memory" | "sqlite" | "postgres"

    # PostgreSQL connection
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ops_agent"
    postgres_user: str = ""
    postgres_password: str = ""
    database_url: str = ""  # postgresql+asyncpg://user:password@host:port/db

    # HITL
    hitl_api_port: int = 8001
    hitl_timeout_seconds: int = 300

    # Server ports
    mcp_server_port: int = 8000
    app_server_port: int = 8002
    mcp_server_url: str = "http://127.0.0.1:8000/sse"

    # Agent behaviour
    reflection_confidence_threshold: float = 0.4
    max_reflection_retries: int = 2
    specialist_timeout_seconds: int = 30

    model_config = {"env_file": ".env", "extra": "ignore"}

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        if not self.database_url and self.postgres_user and self.postgres_password:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return self


settings = Settings()

if settings.langsmith_api_key:
    os.environ["LANGSMITH_TRACING"] = str(settings.langsmith_tracing).lower()
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project



