"""
config.py — Application Settings & Environment Variables
=========================================================
Uses Pydantic's BaseSettings to automatically read configuration values
from environment variables or a .env file. This is the single source of
truth for all runtime configuration — API keys, file size limits, model
names, and directory paths.

Usage:
    from config import settings
    print(settings.anthropic_api_key)
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """
    Central configuration class.

    All fields are read from environment variables (case-insensitive).
    If a .env file is present in the working directory, it is loaded
    automatically via the Config inner class below.

    Required variables (app will fail to start without these):
        ANTHROPIC_API_KEY  — Claude API key from console.anthropic.com
        TAVILY_API_KEY     — Tavily Search API key from app.tavily.com

    Optional variables (sensible defaults provided):
        CLAUDE_MODEL       — Which Claude model to use (default: claude-sonnet-4-6)
        DATABASE_URL       — SQLAlchemy connection string (default: local SQLite)
        MAX_FILE_SIZE      — Max receipt upload size in bytes (default: 20 MB)
        CHROMA_DIR         — Where to persist ChromaDB vector data
        POLICY_DOCS_DIR    — Where to store uploaded corporate policy PDFs
        POLICY_DOC_MAX_SIZE— Max policy PDF upload size in bytes (default: 50 MB)
    """

    # ── Required: AI service credentials ──────────────────────────────────
    anthropic_api_key: str   # Anthropic Claude API key (Vision + tool-use)
    tavily_api_key: str      # Tavily web search API key (live GSA/IRS lookups)

    # ── Database ───────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./expense_reports.db"
    # SQLAlchemy connection string. Defaults to a local SQLite file.
    # Can be swapped to PostgreSQL for production: postgresql://user:pass@host/db

    # ── File upload limits ─────────────────────────────────────────────────
    upload_dir: str = "./uploads"            # Where receipt images are saved
    reports_dir: str = "./reports"           # Where generated PDFs are saved
    max_file_size: int = 20971520            # 20 MB in bytes (20 * 1024 * 1024)

    # ── AI model selection ─────────────────────────────────────────────────
    claude_model: str = "claude-sonnet-4-6"  # Claude model used for all AI calls

    # ── Debug mode ─────────────────────────────────────────────────────────
    debug: bool = True  # Set to False in production

    # ── RAG / ChromaDB settings ────────────────────────────────────────────
    chroma_dir: str = "./chroma_db"          # Persistent ChromaDB storage directory
    policy_docs_dir: str = "./policy_docs"   # Uploaded policy PDF storage directory
    policy_doc_max_size: int = 52428800      # 50 MB in bytes (50 * 1024 * 1024)

    class Config:
        # Load values from .env file if it exists.
        # Variables in the environment always take precedence over .env values.
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    """
    Return the application settings singleton.

    The @lru_cache decorator ensures Settings is only instantiated once
    per process — the .env file is only read on the first call, and the
    same Settings object is returned on every subsequent call. This makes
    config access cheap and consistent throughout the app.
    """
    return Settings()


# Module-level convenience alias.
# Import this directly: `from config import settings`
settings = get_settings()
