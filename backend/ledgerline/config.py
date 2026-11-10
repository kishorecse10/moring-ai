"""Runtime configuration, read from environment variables (and a .env file at the repo root)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

USD_TO_INR = 88.0  # finance's planning rate


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_model: str
    anthropic_api_key: str | None
    openai_base_url: str
    openai_api_key: str | None
    db_path: str
    data_dir: Path
    docs_dir: Path


def get_settings() -> Settings:
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "anthropic"),
        llm_model=os.getenv("LLM_MODEL", "claude-opus-5-5"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        db_path=os.getenv("LEDGERLINE_DB", str(REPO_ROOT / "backend" / "ledgerline.db")),
        data_dir=Path(os.getenv("LEDGERLINE_DATA", str(REPO_ROOT / "data"))),
        docs_dir=REPO_ROOT / "docs",
    )
