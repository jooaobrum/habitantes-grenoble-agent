"""CLI: parse + classify (shared, unchanged) then build the Mentions file.

Run with `make mentions`. Parallel to ingestion/pipeline.py; does not touch the
Q&A pairing, synthesis or load steps.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from ingestion.config import settings
from ingestion.extract.whatsapp import run_parser
from ingestion.pipeline import cleanup_expired_artifacts
from ingestion.suggestions.build import run_suggestions_builder
from ingestion.suggestions.mentions import MENTIONS_FILENAME, run_mentions_builder

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parents[2]


def _retention_cleanup() -> None:
    """Same retention sweep the Q&A ingest runs after a successful load."""
    cleanup_expired_artifacts(
        data_dir=ROOT_DIR / settings.data_dir,
        artifacts_dir=ROOT_DIR / settings.artifacts_dir,
        retention_days=settings.artifacts_retention_days,
    )


async def run_mentions_pipeline() -> Path | None:
    root_dir = ROOT_DIR
    input_chat = root_dir / settings.data_dir / settings.input_file
    load_dotenv(root_dir / ".env")
    if not input_chat.exists():
        logger.error("Input chat file not found: %s", input_chat)
        return None

    chat_dir = root_dir / settings.artifacts_dir / input_chat.stem
    chat_dir.mkdir(parents=True, exist_ok=True)

    classified = run_parser(
        chat_path=input_chat,
        output_dir=chat_dir,
        timestamp_format=settings.parser.timestamp_format,
    )
    result = await run_mentions_builder(
        input_csv=classified,
        output_dir=chat_dir,
        thread_gap_h=settings.qa.thread_gap_h,
        jev=settings.jev,
        suggestions=settings.suggestions,
        extraction=settings.mention_extraction,
    )
    _retention_cleanup()
    return result


async def run_suggestions_pipeline() -> int:
    """Mentions file -> Suggestions file -> Clusters -> Suggestions collection."""
    load_dotenv(ROOT_DIR / ".env")
    chat_dir = ROOT_DIR / settings.artifacts_dir / Path(settings.input_file).stem
    loaded = await run_suggestions_builder(
        mentions_path=chat_dir / MENTIONS_FILENAME,
        output_dir=chat_dir,
        suggestions=settings.suggestions,
        llm_cfg=settings.suggestion_llm,
    )
    _retention_cleanup()
    return loaded


async def _main(stage: str) -> None:
    if stage in ("mentions", "all"):
        await run_mentions_pipeline()
    if stage in ("suggestions", "all"):
        await run_suggestions_pipeline()


def rebuild_all() -> None:
    """Public entry point: rebuild Mentions, Suggestions and the collection."""
    asyncio.run(_main("all"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stage", choices=["mentions", "suggestions", "all"], default="mentions"
    )
    asyncio.run(_main(ap.parse_args().stage))
