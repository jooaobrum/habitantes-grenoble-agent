"""Jev classifier: labels a Q&A pair's value/topic/outdated/needs_review.

Jev (TypeSafe) is called through OpenRouter's decisions endpoint. Low-confidence
answers and call failures fall back to the heuristic tier from qa_pairs.
Wired into ingestion as the value/topic gate (see qa_pairs and pipeline).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "~typesafe/jev-latest"
DEFAULT_BASE_URL = "https://openrouter.ai/api/alpha/decisions"


VALUE_CRITERIA = {
    "HIGH": "common problem for newcomers, not a one-off, rich and complete answer that can be reused as-is",
    "MEDIUM": "still helps newcomers but the answer is partial, or the thread is poorly organized",
    "LOW": "personal, one-off, only relevant to that moment, or a bad/low-quality answer",
    "UNKNOWN": "cannot be judged from the given state",
}

TOPICS = [
    "Visa & Residency",
    "Banking & Finance",
    "Housing & CAF",
    "Health & Insurance",
    "University & Studies",
    "Work & Internship",
    "Documents & Bureaucracy",
    "Daily Life & Services",
    "Travel & Transport",
    "Integration & Language",
    "Ski & Trekking",
    "Food & Restaurants",
    "Sports & Activities",
    "Nightlife & Events",
    "Neighbourhood & Safety",
    "Marketplace & Buy/Sell",
    "Hair & Beauty",
    "Pets & Animals",
    "Phone & Telecom",
    "General",
]


def flatten_context(context: Any) -> List[str]:
    """Reduce context to message text only. The `user` field is never sent."""
    if not context:
        return []
    if isinstance(context, str):
        return [context]
    out: List[str] = []
    for item in context:
        if isinstance(item, dict):
            msg = item.get("message")
            if msg:
                out.append(str(msg))
        elif item:
            out.append(str(item))
    return out


def _questions() -> Dict[str, Any]:
    return {
        "value": {
            "type": "choice",
            "instructions": (
                "How valuable is this question+answer pair for helping many newcomers "
                "(Brazilian expats in Grenoble, France) with a common, non-personal "
                "problem? A short answer can still be complete: do not penalise brevity."
            ),
            "criteria": VALUE_CRITERIA,
        },
        "topic": {
            "type": "choice",
            "instructions": "Which category best matches what the question is actually about?",
            "criteria": {t: t for t in TOPICS},
        },
        "outdated": {
            "type": "noul",
            "instructions": "Does the answer reference COVID rules, time-limited policies, or information likely outdated by now?",
        },
        "needs_review": {
            "type": "noul",
            "instructions": "Is the answer ambiguous, conflicting, or legal/visa/tax guidance that a human should double check?",
        },
    }


def _heuristic_fallback(
    row: Dict[str, Any], source: str = "jev_unavailable"
) -> Dict[str, Any]:
    """Heuristic tier proved unreliable (see JEV_BENCHMARK), so never trust it
    as the value: unclassifiable pairs become UNKNOWN and are not ingested."""
    result = row.copy()
    result.update(
        {
            "value": "UNKNOWN",
            "value_confidence": None,
            "value_probabilities": None,
            "topic": row.get("topic"),
            "jev_outdated": None,
            "jev_needs_review": None,
            "value_source": source,
        }
    )
    return result


async def classify_qa(
    client: httpx.AsyncClient,
    row: Dict[str, Any],
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    ingest_threshold: float = 0.6,
    high_threshold: float = 0.3,
    max_retries: int = 4,
    retry_base_sleep_s: float = 1.5,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    """Label one Q&A pair with Jev; never raises, always returns a record.

    Value is bucketed from Jev's probabilities (see docs/JEV_CALIBRATION.md):
    HIGH if P(HIGH) >= high_threshold, MEDIUM if P(HIGH)+P(MEDIUM) >=
    ingest_threshold, else LOW. A failed call yields UNKNOWN (not ingested).
    """
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        logger.error("OPENROUTER_API_KEY not set; using heuristic fallback")
        return _heuristic_fallback(row)
    payload = {
        "model": model,
        "state": {
            "question": row.get("question", ""),
            "answer": row.get("answer", ""),
            "context": flatten_context(row.get("context")),
        },
        "questions": _questions(),
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    answers: Optional[Dict[str, Any]] = None
    for attempt in range(max_retries):
        try:
            resp = await client.post(
                base_url, headers=headers, json=payload, timeout=timeout_s
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            answers = data["answers"]
            value = answers["value"]
            topic = answers["topic"]
            break
        except Exception as e:
            permanent = (
                isinstance(e, httpx.HTTPStatusError)
                and 400 <= e.response.status_code < 500
                and e.response.status_code not in (408, 429)
            )
            if permanent or attempt == max_retries - 1:
                logger.error(
                    "Final Jev failure for thread %s: %s", row.get("thread_id"), e
                )
                return _heuristic_fallback(row)
            sleep_time = (retry_base_sleep_s**attempt) + random.uniform(0, 0.5)
            logger.warning(
                "Retry %s for thread %s due to %s. Sleeping %.2fs",
                attempt + 1,
                row.get("thread_id"),
                e,
                sleep_time,
            )
            await asyncio.sleep(sleep_time if retry_base_sleep_s else 0)
    else:
        return _heuristic_fallback(row)

    probs = value.get("probabilities") or {}
    p_high = float(probs.get("HIGH", 0.0))
    p_ingest = p_high + float(probs.get("MEDIUM", 0.0))
    if p_high >= high_threshold:
        bucket = "HIGH"
    elif p_ingest >= ingest_threshold:
        bucket = "MEDIUM"
    else:
        bucket = "LOW"
    confidence = float(value.get("confidence", 0.0))

    result = row.copy()
    result.update(
        {
            "value": bucket,
            "value_confidence": confidence,
            "value_probabilities": value.get("probabilities"),
            "topic": topic["choice"],
            "jev_outdated": float(answers.get("outdated", {}).get("noul", 0)) >= 0.5,
            "jev_needs_review": float(answers.get("needs_review", {}).get("noul", 0))
            >= 0.5,
            "value_source": "jev",
        }
    )
    return result
