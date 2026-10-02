"""Loader for the Suggestions collection: one point per Cluster entry.

Rebuilds a collection that is independent of the Q&A one (only the named
collection is ever deleted/created). Embedders are injectable so tests need no
network or model download.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Callable, List, Sequence

from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from habitantes.domain.suggestions import ClusterEntry
from habitantes.domain.tools import enrich_bm25_input, strip_accents
from habitantes.domain.tools._embedding import _embed_texts
from ingestion.load.qdrant import ensure_collection, upsert_points

logger = logging.getLogger(__name__)

DenseEmbed = Callable[[List[str]], List[List[float]]]
SparseEmbed = Callable[[List[str]], List[qmodels.SparseVector]]


def build_dense_text(entry: ClusterEntry) -> str:
    """Summary plus every member's Items (so a place named once for an item is found)."""
    items = " ".join(i for m in entry.members for i in m.items)
    return f"{entry.summary} {items}".strip()


def build_sparse_text(entry: ClusterEntry) -> str:
    """Items plus every member name, accent-stripped and BM25-enriched."""
    parts = [i for m in entry.members for i in m.items] + [
        m.name for m in entry.members
    ]
    return enrich_bm25_input(strip_accents(" ".join(parts)))


def cluster_point_id(entry: ClusterEntry) -> str:
    return hashlib.md5(f"{entry.kind.value}|{entry.label}".encode("utf-8")).hexdigest()


def make_payload(entry: ClusterEntry, sparse_text: str) -> dict:
    payload = entry.model_dump(mode="json")
    payload["sparse_text"] = sparse_text
    return payload


def _default_sparse_embed() -> SparseEmbed:
    model = SparseTextEmbedding(model_name="Qdrant/bm25")

    def embed(texts: List[str]) -> List[qmodels.SparseVector]:
        return [
            qmodels.SparseVector(indices=sv.indices.tolist(), values=sv.values.tolist())
            for sv in model.embed(texts)
        ]

    return embed


def load_clusters(
    clusters: Sequence[ClusterEntry],
    qclient: QdrantClient,
    collection_name: str,
    dense_embed: DenseEmbed | None = None,
    sparse_embed: SparseEmbed | None = None,
    batch_size: int = 64,
) -> int:
    """Rebuild `collection_name` from Cluster entries; returns points written."""
    if not clusters:
        logger.warning("No Cluster entries to load.")
        return 0
    dense_embed = dense_embed or _embed_texts
    sparse_embed = sparse_embed or _default_sparse_embed()

    first = True
    for i in range(0, len(clusters), batch_size):
        batch = clusters[i : i + batch_size]
        dense_vecs = dense_embed([build_dense_text(c) for c in batch])
        if first:
            ensure_collection(
                qclient, collection_name, len(dense_vecs[0]), overwrite=True
            )
            first = False
        sparse_texts = [build_sparse_text(c) for c in batch]
        upsert_points(
            qclient,
            collection_name,
            [cluster_point_id(c) for c in batch],
            dense_vecs,
            sparse_embed(sparse_texts),
            [make_payload(c, st) for c, st in zip(batch, sparse_texts)],
        )
    logger.info("Loaded %d Cluster entries into %s", len(clusters), collection_name)
    return len(clusters)
