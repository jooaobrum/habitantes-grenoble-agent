"""Mentions file -> Suggestions file -> Cluster entries -> Suggestions collection.

Rebuilds only the Suggestions collection (the Q&A one is never touched).
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Optional

import httpx
from qdrant_client import QdrantClient

from ingestion.load.suggestions import DenseEmbed, SparseEmbed, load_clusters
from ingestion.suggestions.clusters import build_clusters
from ingestion.suggestions.mentions import read_mentions
from ingestion.suggestions.merge import merge_variants
from ingestion.suggestions.suggestions import (
    SUGGESTIONS_FILENAME,
    aggregate,
    read_suggestions,
    write_suggestions,
)

logger = logging.getLogger(__name__)


async def run_suggestions_builder(
    mentions_path: Path,
    output_dir: Path,
    suggestions: Any,
    llm_cfg: Any,
    qclient: Optional[QdrantClient] = None,
    llm_client: Optional[httpx.AsyncClient] = None,
    dense_embed: Optional[DenseEmbed] = None,
    sparse_embed: Optional[SparseEmbed] = None,
    today: Optional[date] = None,
    from_suggestions_file: bool = False,
) -> int:
    """Return the number of Cluster entries loaded.

    `from_suggestions_file=True` rebuilds from the stored suggestions file
    (skips merge) so a rebuild never needs the chat or the Mentions file.
    """
    if not from_suggestions_file and not mentions_path.exists():
        logger.error("Mentions file not found: %s (run `make mentions`)", mentions_path)
        return 0
    own = llm_client is None
    client = llm_client or httpx.AsyncClient()
    try:
        sugg_path = output_dir / SUGGESTIONS_FILENAME
        if from_suggestions_file:
            stored = read_suggestions(sugg_path)
        else:
            merged = await merge_variants(read_mentions(mentions_path), llm_cfg, client)
            stored = aggregate(merged)
            output_dir.mkdir(parents=True, exist_ok=True)
            write_suggestions(sugg_path, stored)
            logger.info("Saved %d suggestions to %s", len(stored), sugg_path)
        clusters = await build_clusters(stored, suggestions, llm_cfg, client, today)
    finally:
        if own:
            await client.aclose()

    qclient = qclient or QdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        api_key=os.getenv("QDRANT_API_KEY"),
    )
    return load_clusters(
        clusters,
        qclient,
        suggestions.collection_name,
        dense_embed=dense_embed,
        sparse_embed=sparse_embed,
    )
