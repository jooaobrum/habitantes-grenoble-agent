"""CLI: parse + classify (shared, unchanged) then build the Mentions file.

Run with `make mentions`. Parallel to ingestion/pipeline.py; does not touch the
Q&A pairing, synthesis or load steps.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

from ingestion.config import settings
from ingestion.extract.whatsapp import run_parser
from ingestion.suggestions.mentions import run_mentions_builder

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


async def run_mentions_pipeline() -> Path | None:
    root_dir = Path(__file__).parents[2]
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
    return await run_mentions_builder(
        input_csv=classified,
        output_dir=chat_dir,
        thread_gap_h=settings.qa.thread_gap_h,
        jev=settings.jev,
        suggestions=settings.suggestions,
        extraction=settings.mention_extraction,
    )


if __name__ == "__main__":
    asyncio.run(run_mentions_pipeline())
