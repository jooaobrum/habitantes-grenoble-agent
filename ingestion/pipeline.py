from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from ingestion.config import settings
from ingestion.extract.whatsapp import run_parser
from ingestion.load.qdrant import run_qdrant_loader
from ingestion.preprocess.qa_pairs import run_qa_builder
from ingestion.preprocess.synthesis import run_synthesis_batch

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# Intermediate artifact filenames that still carry names/numbers (see
# docs/PRIVACIDADE.md) — the final Qdrant knowledge base is unaffected.
_INTERMEDIATE_GLOBS = (
    "classified.csv",
    "qa_pairs*.json",
    "qa_pairs*.csv",
    "synthesis_results.jsonl",
)


def cleanup_expired_artifacts(
    data_dir: Path, artifacts_dir: Path, retention_days: int
) -> None:
    """Delete raw WhatsApp exports and per-chat intermediate artifacts once
    they're older than retention_days. Mirrors the loguru rotation/retention
    already applied to logs/interactions.jsonl, but for ingestion files."""
    if retention_days <= 0:
        return

    cutoff = time.time() - retention_days * 86400

    for txt_file in data_dir.glob("*.txt"):
        if txt_file.stat().st_mtime < cutoff:
            logger.info("Retention: deleting expired raw export %s", txt_file)
            txt_file.unlink()

    if not artifacts_dir.exists():
        return

    for chat_dir in artifacts_dir.iterdir():
        if not chat_dir.is_dir() or chat_dir.name == "concat":
            continue
        for pattern in _INTERMEDIATE_GLOBS:
            for f in chat_dir.glob(pattern):
                if f.stat().st_mtime < cutoff:
                    logger.info("Retention: deleting expired artifact %s", f)
                    f.unlink()


async def run_pipeline():
    """
    Run the full ingestion pipeline:
    1. Extract (WhatsApp parse + classify)
    2. Preprocess (QA pairs + scoring)
    3. Synthesis (LLM summary)
    4. Load (Qdrant vectors)
    """
    root_dir = Path(__file__).parents[1]
    data_dir = root_dir / settings.data_dir
    artifacts_dir = root_dir / settings.artifacts_dir
    input_chat = data_dir / settings.input_file

    load_dotenv(root_dir / ".env")

    if not input_chat.exists():
        logger.error("Input chat file not found: %s", input_chat)
        return

    # Standardize: use chat stem as parent folder for all artifacts
    chat_id = input_chat.stem
    chat_artifacts_dir = artifacts_dir / chat_id
    chat_artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Extraction (WhatsApp)
    logger.info("── Step 1: Extraction ───────────────────")
    classified_path = run_parser(
        chat_path=input_chat,
        output_dir=chat_artifacts_dir,
        timestamp_format=settings.parser.timestamp_format,
    )

    # 2. Preprocessing (QA Pairs)
    logger.info("── Step 2: QA Pairing ───────────────────")
    qa_path = run_qa_builder(
        input_csv=classified_path,
        output_dir=chat_artifacts_dir,
        thread_gap_h=settings.qa.thread_gap_h,
        answer_window_h=settings.qa.answer_window_h,
        context_window=settings.qa.context_window,
        tier_high=settings.qa.tier_high,
        tier_medium=settings.qa.tier_medium,
    )

    # 3. Synthesis (Only high/medium tiers)
    logger.info("── Step 3: Synthesis ────────────────────")
    import json

    with qa_path.open("r", encoding="utf-8") as f:
        all_qa = json.load(f)

    # Filter by tier and optional date
    to_synthesize = [qa for qa in all_qa if qa.get("tier") in ("high", "medium")]

    if settings.synthesis.start_time:
        st = settings.synthesis.start_time
        to_synthesize = [qa for qa in to_synthesize if qa["question_time"] >= st]

    if settings.synthesis.end_time:
        et = settings.synthesis.end_time
        to_synthesize = [qa for qa in to_synthesize if qa["question_time"] <= et]

    logger.info("Total items to synthesize: %d", len(to_synthesize))

    synthesis_path = await run_synthesis_batch(
        rows=to_synthesize,
        prompt_path=root_dir / settings.synthesis.prompt_path,
        output_dir=chat_artifacts_dir,
        model=settings.synthesis.model,
        temperature=settings.synthesis.temperature,
        max_retries=settings.synthesis.max_retries,
        retry_base_sleep_s=settings.synthesis.retry_base_sleep_s,
        overwrite=settings.synthesis.overwrite,
        base_url=settings.synthesis.base_url,
    )

    # 4. Loading (Qdrant)
    logger.info("── Step 4: Loading ──────────────────────")
    # Save global concat file for combined inspection across all chat sources
    concat_path = None
    if settings.load.save_concat_jsonl:
        concat_dir = artifacts_dir / "concat"
        concat_dir.mkdir(parents=True, exist_ok=True)
        concat_path = concat_dir / "filtered_concat.jsonl"

    run_qdrant_loader(
        input_files=[synthesis_path],
        collection_name=settings.load.collection_name,
        dense_batch_size=settings.load.dense_batch_size,
        qdrant_upsert_batch=settings.load.qdrant_upsert_batch,
        overwrite_collection=settings.load.overwrite_collection,
        save_concat_jsonl=concat_path,
    )

    # 5. Retention: drop raw/intermediate artifacts past their retention window
    # (only after a successful load — they're the source of truth to rebuild).
    logger.info("── Step 5: Retention cleanup ────────────")
    cleanup_expired_artifacts(
        data_dir=data_dir,
        artifacts_dir=artifacts_dir,
        retention_days=settings.artifacts_retention_days,
    )

    logger.info("── Pipeline Complete ────────────────────")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
