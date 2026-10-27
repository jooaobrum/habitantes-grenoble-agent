"""Tiny JSON-mode chat-completion helper (OpenRouter) shared by merge + summary."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


async def chat_json(
    client: httpx.AsyncClient,
    prompt: str,
    cfg: Any,
    schema: Optional[Dict[str, Any]] = None,
    timeout_s: float = 60.0,
) -> Optional[Dict[str, Any]]:
    """Return the parsed JSON object the model answered, or None (never raises)."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        logger.error("OPENROUTER_API_KEY not set; LLM step skipped")
        return None
    payload: Dict[str, Any] = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": (
            {"type": "json_schema", "json_schema": schema}
            if schema
            else {"type": "json_object"}
        ),
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(cfg.max_retries):
        try:
            resp = await client.post(
                f"{cfg.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout_s,
            )
            resp.raise_for_status()
            data = json.loads(resp.json()["choices"][0]["message"]["content"])
            if isinstance(data, dict):
                return data
            raise ValueError("expected a JSON object")
        except Exception as e:
            permanent = (
                isinstance(e, httpx.HTTPStatusError)
                and 400 <= e.response.status_code < 500
                and e.response.status_code not in (408, 429)
            )
            if permanent or attempt == cfg.max_retries - 1:
                logger.error("LLM call failed: %s", e)
                return None
            if cfg.retry_base_sleep_s:
                await asyncio.sleep(
                    cfg.retry_base_sleep_s**attempt + random.uniform(0, 0.5)
                )
    return None
