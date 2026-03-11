import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CategoryEntry(BaseModel):
    """Single category: Portuguese display name + English Qdrant filter value."""

    pt_name: str  # shown to users
    en_name: str  # used for Qdrant category filter (must match ingestion payload)


class LLMConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    model_name: str = "gpt-4o-mini"
    embedding_model_name: str = "intfloat/multilingual-e5-small"
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")


class VectorStoreConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    collection_name: str = "qa_base"
    qdrant_url: str = "http://qdrant:6333"


class ApiConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    log_level: str = "INFO"
    rate_limit_per_hour: int = 100
    max_tokens_per_response: int = 1024
    request_timeout_seconds: int = 30
    eval_gate_enabled: bool = True


class TelegramConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    api_url: str = "http://api:8000"
    rate_limit_per_minute: int = 10
    max_message_length: int = 2000


class SearchConfig(BaseModel):
    dense_prefetch_k: int = 80
    sparse_prefetch_k: int = 120
    fused_k: int = 50
    top_k: int = 5
    w_dense: float = 0.7
    w_sparse: float = 0.3
    rrf_k: int = 60


class RankingConfig(BaseModel):
    anchor_bonus: float = 0.05
    rerank_top_k: int = 40
    date_decay_lambda: float = 0.0005
    min_token_length: int = 4


class AgentConfig(BaseModel):
    max_react_iterations: int = 5
    max_history: int = 5
    temperature: float = 0.0


class CacheConfig(BaseModel):
    enabled: bool = True
    max_size: int = 256
    ttl_seconds: int = 3600


class LoggingConfig(BaseModel):
    interaction_path: str = "logs/interactions.jsonl"
    rotation: str = "10 MB"
    retention: str = "30 days"


class Settings(BaseSettings):
    """
    Main Settings class for the application.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMConfig
    vector_store: VectorStoreConfig
    api: ApiConfig
    telegram: TelegramConfig
    search: SearchConfig = SearchConfig()
    ranking: RankingConfig = RankingConfig()
    agent: AgentConfig = AgentConfig()
    cache: CacheConfig = CacheConfig()
    logging: LoggingConfig = LoggingConfig()
    categories: list[CategoryEntry] = []
    app_env: str = Field("dev", alias="APP_ENV")


def deep_update(base: dict, update: dict) -> dict:
    """Recursively update a dictionary."""
    for k, v in update.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            base[k] = deep_update(base[k], v)
        else:
            base[k] = v
    return base


@lru_cache()
def load_settings() -> Settings:
    """
    Load settings from YAML, apply environment overrides from YAML,
    and then override with terminal/system environment variables.
    """
    # 0. Load .env file into os.environ so secrets are available below
    from dotenv import load_dotenv

    root_dir = Path(__file__).parents[3]
    load_dotenv(root_dir / ".env", override=False)

    # 1. Load Base YAML
    # CONFIG_DIR env var allows overriding the config directory path (e.g. in Docker)
    config_dir = Path(os.environ.get("CONFIG_DIR", str(root_dir / "config")))
    config_path = config_dir / "base.yaml"

    with open(config_path, "r") as f:
        config_data = yaml.safe_load(f)

    # 2. Apply YAML environment specifics
    app_env = os.environ.get("APP_ENV", "dev")
    env_configs = config_data.get("environments", {})
    env_specific = env_configs.get(app_env, {})

    # Merge env-specific into base config
    config_data = deep_update(config_data, env_specific)

    # 3. Manual override with high-priority environment variables
    # (Matches the mapping from previous version but includes APP_ENV)

    # Secrets
    if "OPENAI_API_KEY" in os.environ:
        config_data.setdefault("llm", {})["openai_api_key"] = os.environ[
            "OPENAI_API_KEY"
        ]
    if "TELEGRAM_BOT_TOKEN" in os.environ:
        config_data.setdefault("telegram", {})["bot_token"] = os.environ[
            "TELEGRAM_BOT_TOKEN"
        ]

    # Other Overrides
    env_map = {
        "MODEL_NAME": ("llm", "model_name"),
        "EMBEDDING_MODEL_NAME": ("llm", "embedding_model_name"),
        "QDRANT_URL": ("vector_store", "qdrant_url"),
        "COLLECTION_NAME": ("vector_store", "collection_name"),
        "LOG_LEVEL": ("api", "log_level"),
        "RATE_LIMIT_PER_HOUR": ("api", "rate_limit_per_hour"),
        "EVAL_GATE_ENABLED": ("api", "eval_gate_enabled"),
        "API_URL": ("telegram", "api_url"),
    }

    for env_key, (section, key) in env_map.items():
        if env_key in os.environ:
            val = os.environ[env_key]
            # Simple type conversion for known bool/int
            if key == "eval_gate_enabled":
                val = val.lower() in ("true", "1", "yes")
            elif key == "rate_limit_per_hour":
                val = int(val)
            config_data.setdefault(section, {})[key] = val

    return Settings(**config_data)
