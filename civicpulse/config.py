from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("CIVICPULSE_DB_PATH", "core_civic.db")
    public_data_dir: Path = Path(os.getenv("CIVICPULSE_PUBLIC_DATA_DIR", "public/data"))
    public_geo_dir: Path = Path(os.getenv("CIVICPULSE_PUBLIC_GEO_DIR", "public/geo"))
    config_dir: Path = Path(os.getenv("CIVICPULSE_CONFIG_DIR", "config/jurisdictions"))
    onedrive_backup_dir: str = os.getenv("ONEDRIVE_BACKUP_DIR", "")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    request_timeout: int = int(os.getenv("CIVICPULSE_HTTP_TIMEOUT", "15"))
    user_agent: str = os.getenv(
        "CIVICPULSE_USER_AGENT",
        "Mozilla/5.0 (compatible; CivicPulseBot/2.0; +https://civics-d03.pages.dev)",
    )

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        }


SETTINGS = Settings()
