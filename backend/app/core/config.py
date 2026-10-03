from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TRUSTBATTLE Backend"
    api_v1_prefix: str = "/api/v1"
    debug: bool = Field(default_factory=lambda: os.getenv("DEBUG", "1") == "1")

    allowed_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    )

    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            f"sqlite:///{REPO_ROOT / 'data' / 'trustbattle.db'}",
        )
    )

    repo_root: Path = REPO_ROOT
    data_dir: Path = REPO_ROOT / "data"
    models_dir: Path = REPO_ROOT / "models"
    attacks_dir: Path = REPO_ROOT / "data" / "attacks"
    synthetic_dir: Path = REPO_ROOT / "data" / "synthetic"

    ws_playback_speed: float = Field(
        default_factory=lambda: float(os.getenv("WS_PLAYBACK_SPEED", "1.0"))
    )
    ws_sleep_s: float = Field(
        default_factory=lambda: float(os.getenv("WS_SLEEP_S", "0.1"))
    )


settings = Settings()
