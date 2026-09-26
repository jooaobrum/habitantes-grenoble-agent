"""Jev classifier: labels a Q&A pair's value/topic/outdated/needs_review.

Jev (TypeSafe) is called through OpenRouter's decisions endpoint. Low-confidence
answers and call failures fall back to the heuristic tier from qa_pairs.
Not yet wired into the ingestion pipeline.
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

TIER_TO_VALUE = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}

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


def _heuristic_fallback(row: Dict[str, Any]) -> Dict[str, Any]:
    result = row.copy()
    result.update(
        {
            "value": TIER_TO_VALUE.get(str(row.get("tier", "")).lower(), "UNKNOWN"),
            "value_confidence": None,
            "value_probabilities": None,
            "topic": row.get("topic"),
            "jev_outdated": None,
            "jev_needs_review": None,
            "value_source": "heuristic_fallback",
        }
    )
    return result


async def classify_qa(
    client: httpx.AsyncClient,
    row: Dict[str, Any],
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    confidence_threshold: float = 0.6,
    max_retries: int = 4,
    retry_base_sleep_s: float = 1.5,
    timeout_s: float = 30.0,
) -> Dict[str, Any]:
    """Label one Q&A pair with Jev; never raises, always returns a record.

    Falls back to the heuristic tier (value_source="heuristic_fallback") when
    the call fails after `max_retries` or value confidence is below threshold.
    """
    key = api_key or os.environ["OPENROUTER_API_KEY"]
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
            if attempt == max_retries - 1:
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

    confidence = float(value.get("confidence", 0.0))
    if confidence < confidence_threshold:
        result = _heuristic_fallback(row)
        result["value_confidence"] = confidence
        result["value_probabilities"] = value.get("probabilities")
        return result

    result = row.copy()
    result.update(
        {
            "value": value["choice"],
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
