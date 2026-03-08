from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer
from fastembed import SparseTextEmbedding


from habitantes.domain.tools import enrich_bm25_input, strip_accents

# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Filtering ────────────────────────────────────────────────────────────────


# ── Filtering ────────────────────────────────────────────────────────────────
def should_drop(rec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if rec.get("info_might_be_outdated") is True:
        reasons.append("info_might_be_outdated=true")

    if str(rec.get("category", "")).strip() == "General":
        reasons.append('category="General"')

    key_terms = rec.get("key_terms", None)
    if not isinstance(key_terms, list) or len(key_terms) == 0:
        reasons.append("key_terms=[]")

    if str(rec.get("answer", "")).startswith("Não há "):
        reasons.append('answer starts with "Não há "')

    try:
        conf = float(rec.get("confidence", -1))
    except (ValueError, TypeError):
        conf = -1

    if conf < 0.65:
        reasons.append("confidence<0.65")

    if str(rec.get("tier", "")).strip().lower() == "low":
        reasons.append('tier="low"')

    if rec.get("needs_human_review") is True:
        reasons.append("needs_human_review=true")

    tags = rec.get("tags", [])
    if isinstance(tags, list) and any(
        isinstance(t, str) and re.search(r"\bCOVID[-\s]?19\b", t, re.IGNORECASE)
        for t in tags
    ):
        reasons.append("tags contains COVID-19")

    q = str(rec.get("question", "")).lower()
    time_terms = [
        "hoje",
        "amanhã",
        "ontem",
        "semana que vem",
        "atualmente",
        "agora",
        "recentemente",
        "último mês",
        "última semana",
    ]

    if any(term in q for term in time_terms):
        reasons.append("time-related term in question")

    return (len(reasons) > 0), reasons


# ── Embedding ────────────────────────────────────────────────────────────────
def build_sparse_text(question: str, key_terms: List[str]) -> str:
    kt = " ".join(str(x).strip() for x in (key_terms or []) if str(x).strip())
    raw_text = f"{question} {kt}" if kt else question
    norm_text = strip_accents(raw_text)
    return enrich_bm25_input(norm_text)


def dense_embed_questions(
    model: SentenceTransformer,
    questions: List[str],
    batch_size: int,
) -> List[List[float]]:
    passages = [f"passage: {q}" for q in questions]
    emb = model.encode(
        passages,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return emb.tolist()  # type: ignore


# ── Qdrant Helpers ───────────────────────────────────────────────────────────
def ensure_collection(
    qclient: QdrantClient,
    name: str,
    dense_size: int,
    overwrite: bool,
) -> None:
    existing = None
    try:
        existing = qclient.get_collection(name)
    except Exception:
        existing = None

    if existing and overwrite:
        logger.info("Deleting existing collection: %s", name)
        qclient.delete_collection(name)
        existing = None

    if existing is None:
        logger.info(
            "Creating collection: %s (dense=%d cosine, sparse=enabled)",
            name,
            dense_size,
        )
        qclient.create_collection(
            collection_name=name,
            vectors_config={
                "dense": qmodels.VectorParams(
                    size=dense_size, distance=qmodels.Distance.COSINE
                ),
            },
            sparse_vectors_config={
                "sparse": qmodels.SparseVectorParams(),
            },
        )


def stable_point_id(rec: Dict[str, Any]) -> str:
    src = str(rec.get("source_file", ""))
    tid = str(rec.get("thread_id", ""))
    qt = str(rec.get("question_time", ""))
    q = str(rec.get("question", ""))
    payload = f"{src}|{tid}|{qt}|{q}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def _normalize_str_list(items: Any) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items if isinstance(items, list) else []:
        norm = strip_accents(str(item).strip().lower())
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


def make_payload(
    rec: Dict[str, Any], source_path: Path, sparse_text: str
) -> Dict[str, Any]:
    payload = dict(rec)
    payload["key_terms"] = _normalize_str_list(rec.get("key_terms", []))
    payload["tags"] = _normalize_str_list(rec.get("tags", []))
    payload["_meta"] = {"source_path": str(source_path)}
    payload["sparse_text"] = sparse_text
    return payload


def upsert_points(
    qclient: QdrantClient,
    collection: str,
    ids: List[str],
    dense_vecs: List[List[float]],
    sparse_vecs: List[qmodels.SparseVector],
    payloads: List[Dict[str, Any]],
) -> None:
    points = [
        qmodels.PointStruct(id=pid, vector={"dense": dvec, "sparse": svec}, payload=pl)
        for pid, dvec, svec, pl in zip(ids, dense_vecs, sparse_vecs, payloads)
    ]
    qclient.upsert(collection_name=collection, points=points)


# ── Main Loader ──────────────────────────────────────────────────────────────
def run_qdrant_loader(
    input_files: List[Path],
    collection_name: str,
    dense_batch_size: int = 64,
    qdrant_upsert_batch: int = 128,
    overwrite_collection: bool = False,
    save_concat_jsonl: Optional[Path] = None,
) -> None:
    qdrant_url = os.getenv("QDRANT_URL")
    if not qdrant_url:
        raise EnvironmentError("QDRANT_URL not found in environment")

    qclient = QdrantClient(url=qdrant_url, api_key=os.getenv("QDRANT_API_KEY"))

    dense_model = SentenceTransformer("intfloat/multilingual-e5-large")
    sparse_model = SparseTextEmbedding(model_name="Qdrant/bm25")

    kept: List[Tuple[Dict[str, Any], Path]] = []
    for path in input_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                # Handle both single JSON and JSONL
                if path.suffix == ".jsonl":
                    for line in f:
                        if line.strip():
                            rec = json.loads(line)
                            drop, _ = should_drop(rec)
                            if not drop:
                                kept.append((rec, path))
                else:
                    rec = json.loads(f.read())
                    drop, _ = should_drop(rec)
                    if not drop:
                        kept.append((rec, path))
        except Exception as e:
            logger.warning("Error reading %s: %s", path, e)

    if not kept:
        logger.warning("No records passed filters.")
        return

    # Concat
    if save_concat_jsonl:
        save_concat_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with save_concat_jsonl.open("w", encoding="utf-8") as f:
            for rec, path in kept:
                out = dict(rec)
                out["_meta"] = {"source_path": str(path)}
                f.write(json.dumps(out, ensure_ascii=False) + "\n")

    # Ensure Collection
    test_vec = dense_embed_questions(
        dense_model, [str(kept[0][0]["question"])], batch_size=1
    )[0]
    ensure_collection(qclient, collection_name, len(test_vec), overwrite_collection)

    # Process batches
    for i in range(0, len(kept), dense_batch_size):
        batch = kept[i : i + dense_batch_size]
        q_texts = [str(r[0].get("question", "")) for r in batch]
        sparse_texts = [
            build_sparse_text(q, r[0].get("key_terms", []))
            for q, r in zip(q_texts, batch)
        ]

        d_vecs = dense_embed_questions(dense_model, q_texts, dense_batch_size)
        s_vecs_raw = list(sparse_model.embed(sparse_texts))
        s_vecs = [
            qmodels.SparseVector(indices=sv.indices.tolist(), values=sv.values.tolist())
            for sv in s_vecs_raw
        ]

        ids, payloads = [], []
        for r, st in zip(batch, sparse_texts):
            ids.append(stable_point_id(r[0]))
            payloads.append(make_payload(r[0], r[1], st))

        upsert_points(qclient, collection_name, ids, d_vecs, s_vecs, payloads)
        logger.info("Upserted batch ending at %d", i + len(batch))

    logger.info("Ingestion complete. Total: %d", len(kept))
