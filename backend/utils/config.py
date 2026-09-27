"""Application configuration.

Static configuration comes from environment variables / `.env` (see `.env.example`).
User-adjustable runtime settings (model choice, voice, ...) are stored in SQLite and
layered on top via `backend.storage.database.get_runtime_settings()`.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parents[2]

# Hard guarantee: never let HuggingFace / transformers reach the network at runtime.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(APP_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "local"
    database_path: str = "./data/app.db"

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    output_dir: str = "./outputs"
    project_dir: str = "./projects"
    data_dir: str = "./data"
    brands_dir: str = "./brands"
    templates_dir: str = "./templates"
    models_dir: str = "./models"

    ffmpeg_path: str = ""
    ocr_enabled: bool = True
    tts_enabled: bool = True
    tts_engine: str = "auto"
    piper_path: str = ""
    piper_voice: str = ""

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    max_upload_mb: int = 100

    def resolve(self, value: str) -> Path:
        p = Path(value)
        return (p if p.is_absolute() else APP_ROOT / p).resolve()

    @property
    def db_file(self) -> Path:
        return self.resolve(self.database_path)

    @property
    def outputs_path(self) -> Path:
        return self.resolve(self.output_dir)

    @property
    def projects_path(self) -> Path:
        return self.resolve(self.project_dir)

    @property
    def data_path(self) -> Path:
        return self.resolve(self.data_dir)

    @property
    def documents_path(self) -> Path:
        return self.data_path / "documents"

    @property
    def brands_path(self) -> Path:
        return self.resolve(self.brands_dir)

    @property
    def templates_path(self) -> Path:
        return self.resolve(self.templates_dir)

    @property
    def models_path(self) -> Path:
        return self.resolve(self.models_dir)

    media_dir: str = "./media"

    @property
    def media_path(self) -> Path:
        return self.resolve(self.media_dir)

    def ensure_dirs(self) -> None:
        for p in (
            self.db_file.parent,
            self.outputs_path,
            self.projects_path,
            self.documents_path,
            self.brands_path,
            self.templates_path,
            self.models_path,
            *(self.media_path / sub for sub in ("images", "logos", "icons", "references", "voices", "licenses",
                                                 "thumbs", "processed", "illustrations")),
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
