from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, Field


# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────
class SynthesisResult(BaseModel):
    summary: str = Field(description="Synthetic answer summarizing the solution")
    tags: List[str] = Field(description="Relevant categories/tags")
    verified_answer: bool = Field(description="Was it explicitly confirmed?")
    score: int = Field(description="Confidence score (0-100)")


# ── Prompt Loader ─────────────────────────────────────────────────────────────
def load_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Missing synthesis prompt: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


# ── AI Synthesis ─────────────────────────────────────────────────────────────
async def synthesize_qa(
    client: AsyncOpenAI,
    prompt_template: str,
    row: Dict[str, Any],
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    max_retries: int = 4,
    retry_base_sleep_s: float = 1.5,
) -> Optional[Dict[str, Any]]:
    """
    Calls OpenAI to synthesize a Q&A pair into a clear knowledge item.
    """
    chat_prompt = prompt_template.format(
        topic=row.get("topic", "N/A"),
        question=row.get("question", ""),
        answer=row.get("answer", ""),
        confirmed="YES" if row.get("confirmed") else "NO",
        score=row.get("score", 0),
    )

    for attempt in range(max_retries):
        try:
            resp = await client.beta.chat.completions.parse(
                model=model,
                messages=[{"role": "user", "content": chat_prompt}],
                response_format=SynthesisResult,
                temperature=temperature,
            )
            parsed = resp.choices[0].message.parsed
            if not parsed:
                return None

            result = row.copy()
            result.update(
                {
                    "synthetic_answer": parsed.summary,
                    "tags": parsed.tags,
                    "verified_by_llm": parsed.verified_answer,
                    "score_llm": parsed.score,
                    "synthesized_at": datetime.now().isoformat(),
                }
            )
            return result

        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(
                    "Final synthesis failure for thread %s: %s", row.get("thread_id"), e
                )
                return None

            # Simple exponential backoff
            sleep_time = (retry_base_sleep_s**attempt) + random.uniform(0, 0.5)
            logger.warning(
                "Retry %s for thread %s due to %s. Sleeping %.2fs",
                attempt + 1,
                row.get("thread_id"),
                e,
                sleep_time,
            )
            await asyncio.sleep(sleep_time)

    return None


async def run_synthesis_batch(
    rows: List[Dict[str, Any]],
    prompt_path: Path,
    output_dir: Path,
    model: str = "gpt-4o-mini",
    temperature: float = 0.2,
    max_retries: int = 4,
    retry_base_sleep_s: float = 1.5,
    overwrite: bool = False,
) -> Path:
    """
    Main loop for synthesis. Saves as line-delimited JSON (jsonl).
    """
    # Logic to filter rows by date could be here or outside
    if not rows:
        logger.warning("No rows provided for synthesis.")
        # Create empty file
        out_path = output_dir / "synthesis_results.jsonl"
        out_path.write_text("")
        return out_path

    # Standardized output name: synthesis_results.jsonl
    out_path = output_dir / "synthesis_results.jsonl"

    if out_path.exists() and not overwrite:
        logger.info("Found existing synthesis file: %s", out_path)
        return out_path

    prompt_template = load_prompt(prompt_path)
    client = AsyncOpenAI()  # environment variables used for API key

    synthesized_count = 0
    errors_count = 0

    output_dir.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        # We can use semaphores to control concurrency if needed,
        # but for now we'll do them in small batches or sequentially to avoid rate limits
        # sequentially for simplicity in this refactor
        for row in rows:
            res = await synthesize_qa(
                client=client,
                prompt_template=prompt_template,
                row=row,
                model=model,
                temperature=temperature,
                max_retries=max_retries,
                retry_base_sleep_s=retry_base_sleep_s,
            )
            if res:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
                synthesized_count += 1
            else:
                errors_count += 1

            if (synthesized_count + errors_count) % 10 == 0:
                logger.info(
                    "Progress: %s processed...", synthesized_count + errors_count
                )

    logger.info("Synthesis complete. Saved %s items to %s", synthesized_count, out_path)
    return out_path
