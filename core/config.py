"""Settings loaded from the environment / untracked .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_base_url: str = "http://127.0.0.1:11434"
    # "scripted" = rule-based planner, no model needed (default). "ollama" = Gemma via Ollama.
    planner: str = "scripted"
    ollama_model: str = "gemma3:4b"
    # CPU-only inference (e.g. Ollama in Docker on a Mac) can take minutes on a cold start.
    ollama_timeout_seconds: float = 300.0
    # "memory" = built-in synthetic sales data (default, no database). "postgres" = read-only role.
    sales_backend: str = "memory"
    database_url: str | None = None
    demo_operator_token: str = ""
    max_agent_steps: int = 6
    actiongate_db_path: Path = Path("data/actiongate.sqlite3")
    outbox_path: Path = Path("data/outbox.jsonl")


@lru_cache
def get_settings() -> Settings:
    return Settings()
