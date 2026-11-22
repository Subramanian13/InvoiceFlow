from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "InvoiceFlow API"
    database_url: str = f"sqlite:///{BACKEND_DIR / 'invoiceflow.db'}"
    frontend_origin: str = "http://localhost:5173"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3-flash-preview"
    gemini_timeout_ms: int = 60000
    gemini_max_output_tokens: int = 8192
    upload_max_bytes: int = 10 * 1024 * 1024
    upload_max_pages: int = 10
    invoice_storage_dir: Path = BACKEND_DIR / "storage" / "invoices"
    demo_ap_username: str = "ap-analyst"
    demo_ap_password: str | None = None
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

