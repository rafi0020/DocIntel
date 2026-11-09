"""Central configuration.

Every tunable in the system is read from environment variables (or a `.env`
file) through this one class, so `.env` is the single control surface.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # --- infrastructure -------------------------------------------------
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/docintel"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Path("./storage")
    queue_name: str = "documents"
    # Run jobs inline instead of through Redis (used by tests and the eval runner).
    queue_sync: bool = False
    job_timeout_s: int = 3600
    job_retries: int = 2

    # --- security --------------------------------------------------------
    # When set, every /api request must carry `X-API-Key: <value>`.
    api_key: str | None = None
    cors_origins: str = "http://localhost:3000"
    max_upload_mb: int = 200
    max_files_per_upload: int = 50

    # Master secret that encrypts API keys saved from the UI. If unset, one is generated once and kept in STORAGE_DIR.
    secret_key: str | None = None

    # --- accounts & sessions ----------------------------------------------
    allow_signup: bool = True            # self-service sign-up creates a "reviewer"; admins can change roles
    cookie_secure: bool = False          # set true when the UI is served over HTTPS
    session_hours: int = 12
    remember_days: int = 30
    login_max_attempts: int = 5          # consecutive failures before the account is locked
    login_lock_minutes: int = 10
    # Demo accounts for local use and demonstrations. Disable (SEED_DEMO_USERS=false) in real deployments.
    seed_demo_users: bool = True
    demo_admin_password: str = "Admin#Demo2026"
    demo_reviewer_password: str = "Reviewer#Demo2026"
    demo_viewer_password: str = "Viewer#Demo2026"
    # First administrator for a real deployment: created at start-up if no admin exists yet.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # --- ingestion / OCR -------------------------------------------------
    ocr_engine: Literal["rapidocr", "tesseract"] = "tesseract"
    ocr_dpi: int = 200
    ocr_threads: int = 2
    # A PDF page with fewer extractable characters than this is treated as scanned.
    min_text_chars_per_page: int = 25
    max_pages: int = 2000

    # --- extraction ------------------------------------------------------
    # rules | anthropic | gemini | groq | openai | ollama | openai_compatible
    llm_provider: str = "rules"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None  # required for openai_compatible gateways
    llm_json_mode: bool = True
    llm_temperature: float = 0.0
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 3
    llm_max_chars: int = 14000
    llm_concurrency: int = 4
    # Month/day order used when a date like 03/04/2026 is ambiguous.
    ambiguous_date_order: Literal["MDY", "DMY"] = "MDY"

    # --- validation ------------------------------------------------------
    amount_abs_tolerance: float = 0.02
    # Invoice arithmetic is exact to the cent: tolerance is absolute (+1 cent per line
    # item for per-line rounding). A relative tolerance would hide large errors on big invoices.
    amount_rel_tolerance: float = 0.0
    low_confidence_threshold: float = 0.5
    max_tax_rate: float = 0.5

    # --- search ----------------------------------------------------------
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embeddings_enabled: bool = True
    model_dir: Path | None = None  # embedding model cache (default: STORAGE_DIR/models)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def cache_dir(self) -> Path:
        return self.storage_dir / "cache"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    return s
