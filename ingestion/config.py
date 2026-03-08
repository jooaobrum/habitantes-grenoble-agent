from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ParserConfig(BaseModel):
    timestamp_format: str = "%d/%m/%y, %H:%M:%S"


class QAConfig(BaseModel):
    thread_gap_h: int = 3
    answer_window_h: int = 2
    context_window: int = 5
    tier_high: int = 50
    tier_medium: int = 20


class SynthesisConfig(BaseModel):
    prompt_path: str = "prompts/synthesis_prompt.txt"
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    max_retries: int = 4
    retry_base_sleep_s: float = 1.5
    start_time: Optional[str] = "2024-02-15T00:00:00"
    end_time: Optional[str] = "2027-12-31T23:59:59"
    overwrite: bool = False


class LoadConfig(BaseModel):
    collection_name: str = "habitantes_chat_kb_hybrid_2"
    dense_batch_size: int = 64
    qdrant_upsert_batch: int = 128
    overwrite_collection: bool = False
    save_concat_jsonl: bool = True


class IngestionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: str = "data"
    artifacts_dir: str = "artifacts"
    input_file: str = "chat-19012021-20022026.txt"
    parser: ParserConfig = ParserConfig()
    qa: QAConfig = QAConfig()
    synthesis: SynthesisConfig = SynthesisConfig()
    load: LoadConfig = LoadConfig()


def load_ingestion_settings() -> IngestionSettings:
    """Load ingestion settings from base.yaml."""
    root_dir = Path(__file__).parents[1]
    config_path = root_dir / "config" / "base.yaml"

    if not config_path.exists():
        return IngestionSettings()

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    # 1. Start with the 'ingestion' block
    ingestion_data = config_data.get("ingestion", {})

    # 2. Apply environment-specific overrides if they exist in the YAML
    import os

    app_env = os.environ.get("APP_ENV", "dev")
    env_configs = config_data.get("environments", {})
    env_specific = env_configs.get(app_env, {}).get("ingestion", {})

    # Simple merge of env-specific into ingestion block
    ingestion_data.update(env_specific)

    return IngestionSettings(**ingestion_data)


# Global instance
settings = load_ingestion_settings()
