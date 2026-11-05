from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DocIntel"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    database_url: str = "sqlite:///./data/docintel.db"
    secret_key: str = "change-this-to-a-long-random-string"
    access_token_minutes: int = 720
    cookie_secure: bool = False
    demo_email: str = "admin@docintel.local"
    demo_password: str = "admin12345"
    frontend_origin: str = "http://localhost:3000"

    storage_backend: str = "local"  # local | supabase
    local_storage_dir: str = "./data/uploads"
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "documents"

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_timeout_seconds: int = 90

    ocr_engine: str = "auto"  # auto | rapidocr | tesseract | none
    tesseract_cmd: str = ""

    embedding_provider: str = "auto"  # auto | fastembed | hash
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    max_file_mb: int = 200
    max_files_per_upload: int = 20
    max_pdf_pages: int = 1500

    auto_approve_confidence: float = 0.85
    amount_tolerance: float = 0.01
    line_item_tolerance_pct: float = 0.005

    worker_poll_seconds: float = 1.0
    worker_concurrency: int = 2
    job_stale_seconds: int = 1800

    # Optional: run an in-process worker with the API (single-service demo).
    auto_worker: bool = False

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        # Supabase gives postgresql://...; SQLAlchemy needs an explicit driver.
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        if value.startswith("postgresql://") and "+psycopg" not in value:
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def local_storage_path(self) -> Path:
        return Path(self.local_storage_dir).resolve()

    @property
    def ai_enabled(self) -> bool:
        return bool(self.groq_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
