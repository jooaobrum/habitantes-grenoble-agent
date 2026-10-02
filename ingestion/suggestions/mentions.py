"""Mentions builder: classified chat -> author-free `mentions.jsonl`.

Windows (lexicon) -> Jev yes/no filter -> pseudonymised LLM extraction.
Output: one JSON object per line with exactly the `Mention` fields
(name, kind, polarity, items, context, date, community_business); no author,
no phone number. Q&A artifacts are neither read nor written.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, List, Optional

import httpx
import pandas as pd

from ingestion.preprocess.jev import classify_window
from ingestion.suggestions.extract import Mention, extract_mentions, pseudonymise
from ingestion.suggestions.windows import Window, build_windows

__all__ = ["Mention", "MENTIONS_FILENAME", "run_mentions_builder", "read_mentions"]

logger = logging.getLogger(__name__)

MENTIONS_FILENAME = "mentions.jsonl"


async def extract_all_mentions(
    windows: List[Window],
    jev: Any,
    suggestions: Any,
    extraction: Any,
    jev_client: httpx.AsyncClient,
    llm_client: httpx.AsyncClient,
    concurrency: int = 8,
) -> List[Mention]:
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(w: Window) -> List[Mention]:
        async with sem:
            text, _ = pseudonymise(w)
            verdict = await classify_window(
                jev_client,
                text,
                model=jev.model,
                base_url=jev.base_url,
                cutoff=suggestions.jev_cutoff,
                max_retries=jev.max_retries,
                retry_base_sleep_s=jev.retry_base_sleep_s,
            )
            if verdict is None:
                logger.warning(
                    "Jev failed for window in thread %s; skipped", w.thread_id
                )
                return []
            if not verdict:
                return []
            found = await extract_mentions(
                llm_client,
                w,
                model=extraction.model,
                base_url=extraction.base_url,
                temperature=extraction.temperature,
                max_retries=extraction.max_retries,
                retry_base_sleep_s=extraction.retry_base_sleep_s,
            )
            return found or []

    results = await asyncio.gather(*(one(w) for w in windows))
    return [m for batch in results for m in batch]


async def run_mentions_builder(
    input_csv: Path,
    output_dir: Path,
    thread_gap_h: int,
    jev: Any,
    suggestions: Any,
    extraction: Any,
    jev_client: Optional[httpx.AsyncClient] = None,
    llm_client: Optional[httpx.AsyncClient] = None,
    concurrency: int = 8,
) -> Path:
    """Build `<output_dir>/mentions.jsonl` from a classified chat CSV."""
    df = pd.read_csv(input_csv, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["message"] = df["message"].fillna("")

    windows = build_windows(
        df,
        thread_gap_h,
        suggestions.window_before,
        suggestions.window_after_request,
        suggestions.window_after_other,
    )
    logger.info("Candidate windows: %d", len(windows))

    own_jev, own_llm = jev_client is None, llm_client is None
    jc = jev_client or httpx.AsyncClient()
    lc = llm_client or httpx.AsyncClient()
    try:
        mentions = await extract_all_mentions(
            windows, jev, suggestions, extraction, jc, lc, concurrency
        )
    finally:
        if own_jev:
            await jc.aclose()
        if own_llm:
            await lc.aclose()

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / MENTIONS_FILENAME
    with out_path.open("w", encoding="utf-8") as f:
        for m in mentions:
            f.write(m.model_dump_json() + "\n")
    logger.info("Saved %d mentions to %s", len(mentions), out_path)
    return out_path


def read_mentions(path: Path) -> List[Mention]:
    with path.open(encoding="utf-8") as f:
        return [Mention.model_validate_json(line) for line in f if line.strip()]
