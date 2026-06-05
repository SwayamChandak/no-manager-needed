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
    langchain_tracing_v2: bool = True
    langchain_api_key: str = ""
    langchain_project: str = "ecommerce-ops-agent"

    # Qdrant vector store
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    qdrant_collection: str = "incident_memory"

    # Checkpoint store
    checkpoint_backend: str = "memory"  # "memory" | "sqlite" | "postgres"
    postgres_url: Optional[str] = None

    # HITL
    hitl_api_port: int = 8001
    hitl_timeout_seconds: int = 300

    # Agent behaviour
    reflection_confidence_threshold: float = 0.4
    max_reflection_retries: int = 2
    specialist_timeout_seconds: int = 30

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()



