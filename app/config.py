"""Application settings loaded from environment (Pydantic Settings)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/incident_investigator"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    mcp_tool_timeout_seconds: float = 8.0
    obs_mcp_server_cmd: str = "python -m mcp_observability.server"
    k8s_mcp_server_cmd: str = "python -m mcp_kubernetes.server"

    k8s_namespace: str = "demo"
    kubeconfig_path: str = ""


settings = Settings()
