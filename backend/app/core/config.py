"""Application settings, read from environment / .env (12-factor)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(str(ROOT_DIR / ".env"), str(BACKEND_DIR / ".env")),
                                      env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GLOBX Assess"
    environment: str = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    public_base_url: str = "http://localhost:8000"
    # DEMO_MODE shows OTP codes on screen when no SMTP is configured. Turn OFF for real tests.
    demo_mode: bool = True
    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'oap.sqlite3').as_posix()}"
    storage_dir: str = str(ROOT_DIR / "user-assets")  # what people produce: camera pictures and uploaded answer files. Docker: a volume.

    secret_key: str  # required: set SECRET_KEY in .env (no default, so a known key can never run in production)
    access_token_minutes: int = 15
    refresh_token_hours: int = 12
    otp_minutes: int = 5
    otp_max_attempts: int = 5
    otp_max_sends_per_hour: int = 5
    require_admin_mfa: bool = False

    # SMTP (optional). When empty, mails are kept in the admin "Mail outbox".
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "GLOBX Assess <no-reply@globx.co.in>"
    smtp_tls: bool = True

    # Sandboxes (no Docker). Leave a path empty to auto-detect on PATH.
    sandbox_dir: str = str(BACKEND_DIR / "data" / "sandbox")
    judge_workers: int = 2
    sandbox_python: str = ""
    sandbox_gcc: str = ""
    sandbox_gpp: str = ""
    sandbox_javac: str = ""
    sandbox_java: str = ""
    sandbox_node: str = ""
    sandbox_network_isolation: str = "auto"   # auto | on | off  (Linux: unshare -rn)
    sql_postgres_dsn: str = ""   # e.g. postgresql://judge:pw@localhost:5432/judge
    sql_mysql_dsn: str = ""      # e.g. mysql://judge:pw@localhost:3306/judge
    run_limit_per_question: int = 50
    submit_limit_per_question: int = 20

    # AI provider: none | ollama | openai | azure_openai | gemini | claude
    llm_provider: str = "none"
    llm_ollama_base_url: str = "http://localhost:11434"
    llm_ollama_model: str = "qwen2.5:7b-instruct"
    llm_openai_api_key: str = ""
    llm_openai_model: str = "gpt-4o-mini"
    llm_azure_openai_endpoint: str = ""
    llm_azure_openai_deployment: str = ""
    llm_gemini_api_key: str = ""
    llm_gemini_model: str = "gemini-1.5-flash"
    llm_anthropic_api_key: str = ""
    llm_anthropic_model: str = "claude-3-5-haiku-latest"

    proctor_snapshot_seconds: int = 15
    proctor_retention_days: int = 180

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
