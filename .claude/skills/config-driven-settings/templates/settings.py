"""
settings.py — Pydantic settings loader
Usage:
    from app.core.settings import settings
    print(settings.llm.model)

APP_ENV controls which YAML is loaded: dev (default) | staging | prod
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


# ── Sub-models ──────────────────────────────────────────────────────────────


class AppSettings(BaseModel):
    name: str = "my-agent"
    version: str = "0.1.0"
    log_level: str = "INFO"


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    timeout_seconds: int = 30


class LLMSettings(BaseModel):
    provider: str = "azure_openai"
    model: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout_seconds: int = 10
    max_retries: int = 2


class EmbeddingSettings(BaseModel):
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    batch_size: int = 32


class RetrievalSettings(BaseModel):
    top_k: int = 5
    similarity_threshold: float = 0.70
    collection_name: str = "documents"


class IngestionSettings(BaseModel):
    chunk_size: int = 512
    chunk_overlap: int = 50
    supported_extensions: list[str] = [".pdf"]
    manifest_path: str = "ingestion/manifest.json"


class EvaluationSettings(BaseModel):
    cases_path: str = "tests/eval/cases/"
    min_accuracy: float = 0.75
    max_unsafe_rate: float = 0.0


# ── Main settings ────────────────────────────────────────────────────────────


class Settings(BaseSettings):
    app: AppSettings = AppSettings()
    api: ApiSettings = ApiSettings()
    llm: LLMSettings = LLMSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    retrieval: RetrievalSettings = RetrievalSettings()
    ingestion: IngestionSettings = IngestionSettings()
    evaluation: EvaluationSettings = EvaluationSettings()

    model_config = {"env_nested_delimiter": "__"}


def _load_yaml(env: str) -> dict:
    """Load base.yaml merged with <env>.yaml from config/."""
    config_dir = Path(__file__).parent.parent.parent / "config"
    base = yaml.safe_load((config_dir / "base.yaml").read_text()) or {}
    override_path = config_dir / f"{env}.yaml"
    if override_path.exists():
        override = yaml.safe_load(override_path.read_text()) or {}
        _deep_merge(base, override)
    return base


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "dev")
    data = _load_yaml(env)
    return Settings(**data)


settings = get_settings()
