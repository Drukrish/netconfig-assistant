from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Anchored to the project root so the server can start from any CWD
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "Network Configuration Assistant"
    app_version: str = "0.1.0"
    debug: bool = False

    # Local: Docker Compose Postgres+pgvector. Deployed: AWS RDS. Never
    # hardcoded here — same handling as the Anthropic key in Phase 1's
    # growth-os, a local .env that's gitignored.
    database_url: str

    anthropic_api_key: str = ""  # empty means generation endpoints 503

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    allowed_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
