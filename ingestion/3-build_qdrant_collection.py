from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# pip install qdrant-client sentence-transformers torch
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sentence_transformers import SentenceTransformer
from fastembed import SparseTextEmbedding


# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


# ── Config ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class IngestConfig:
    input_dirs: List[Path]
    collection_name: str

    # Dense embedding (Transformer)
    dense_model_name: str = "intfloat/multilingual-e5-small"  # fast + good PT
    dense_batch_size: int = 64

    # Sparse embedding (FastEmbed BM25)
    sparse_model_name: str = "Qdrant/bm25"

    # Qdrant
    overwrite_collection: bool = False
    qdrant_upsert_batch: int = 128

    # Optional: write filtered concat file for inspection
    save_concat_jsonl: Optional[Path] = None


# ── Filtering rules ──────────────────────────────────────────────────────────
def should_drop(rec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Drop if ANY condition is true:
      - info_might_be_outdated == true
      - category == "General"
      - key_terms == []
      - confidence < 0.65
      - tier == "low"
      - needs_human_review == true
      - answer starts with "Não há "
      - tags contains COVID-19 or COVID
      - time-related
    Missing fields are treated as failing the filter (drop).
    """
    reasons: List[str] = []

    if rec.get("info_might_be_outdated") is True:
        reasons.append("info_might_be_outdated=true")

    if str(rec.get("category", "")).strip() == "General":
        reasons.append('category="General"')

    key_terms = rec.get("key_terms", None)
    if not isinstance(key_terms, list) or len(key_terms) == 0:
        reasons.append("key_terms=[]")

    if rec.get("answer").startswith("Não há "):
        reasons.append('answer starts with "Não há "')

    try:
        conf = float(rec.get("confidence", -1))
    except Exception:
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


# ── IO ───────────────────────────────────────────────────────────────────────
def iter_json_files(input_dirs: List[Path]) -> List[Path]:
    files: List[Path] = []
    for d in input_dirs:
        if not d.exists():
            logger.warning("Input dir does not exist: %s", d)
            continue
        files.extend(sorted(d.rglob("*.json")))
    if not files:
        raise FileNotFoundError("No .json files found in the provided folders.")
    return files


def load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a single JSON object (dict).")
    return data


def build_sparse_text(question: str, key_terms: List[str]) -> str:
    """
    Sparse side = question + KEY TERMS -> normalize -> enrich.
    """
    import sys
    from pathlib import Path

    # Ensure api/src is in path for habitantes import
    project_root = Path(__file__).resolve().parents[1]
    src_path = str(project_root / "api" / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    from habitantes.domain.tools import enrich_bm25_input, strip_accents

    # 1. Concat
    kt = " ".join(str(x).strip() for x in (key_terms or []) if str(x).strip())
    raw_text = f"{question} {kt}" if kt else question

    # 2. Normalize
    norm_text = strip_accents(raw_text)

    # 3. Enrich (normalized)
    return enrich_bm25_input(norm_text)


# ── Dense embedding (Transformer) ────────────────────────────────────────────
def dense_embed_questions(
    model: SentenceTransformer,
    questions: List[str],
    batch_size: int,
) -> List[List[float]]:
    """
    Dense side = ONLY question (as you requested).

    For E5 models:
      - Use prefix "passage: " for stored KB items.
    """
    # E5 expects "passage: ..." for documents
    passages = [f"passage: {q}" for q in questions]
    emb = model.encode(
        passages,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,  # cosine-friendly
    )
    return emb.tolist()  # type: ignore


# ── Qdrant helpers ───────────────────────────────────────────────────────────
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
    else:
        # Basic compatibility check (dense size)
        try:
            # qdrant versions differ in how config is represented; keep it defensive
            current_size = existing.config.params.vectors["dense"].size  # type: ignore
            if int(current_size) != int(dense_size):
                raise ValueError(
                    f"Collection '{name}' exists with dense size {current_size}, "
                    f"but model outputs {dense_size}. Use overwrite_collection=True or change name."
                )
        except Exception:
            logger.warning(
                "Could not validate existing collection vector size; proceeding."
            )


def stable_point_id(rec: Dict[str, Any]) -> str:
    """
    Stable ID so re-runs upsert consistently.
    """
    src = str(rec.get("source_file", ""))
    tid = str(rec.get("thread_id", ""))
    qt = str(rec.get("question_time", ""))
    q = str(rec.get("question", ""))
    payload = f"{src}|{tid}|{qt}|{q}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def make_payload(
    rec: Dict[str, Any], source_path: Path, sparse_text: str
) -> Dict[str, Any]:
    """
    Store original record + provenance + sparse_text (for debugging).
    """
    payload = dict(rec)
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
    points = []
    for pid, dvec, svec, pl in zip(ids, dense_vecs, sparse_vecs, payloads):
        points.append(
            qmodels.PointStruct(
                id=pid,
                vector={"dense": dvec, "sparse": svec},
                payload=pl,
            )
        )
    qclient.upsert(collection_name=collection, points=points)


# ── Main pipeline ────────────────────────────────────────────────────────────
def run_ingest(cfg: IngestConfig) -> None:
    load_dotenv()

    qdrant_url = os.getenv("QDRANT_URL")
    if not qdrant_url:
        raise EnvironmentError(
            "QDRANT_URL not found in environment/.env (e.g. http://localhost:6333)"
        )
    qdrant_api_key = os.getenv("QDRANT_API_KEY")  # optional

    qclient = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)

    # Load embedding models
    logger.info("Loading dense embedding model: %s", cfg.dense_model_name)
    dense_model = SentenceTransformer(cfg.dense_model_name)

    logger.info("Loading sparse embedding model: %s", cfg.sparse_model_name)
    sparse_model = SparseTextEmbedding(model_name=cfg.sparse_model_name)

    # 1) Read + filter
    files = iter_json_files(cfg.input_dirs)
    logger.info(
        "Found %d JSON file(s) across %d folder(s).", len(files), len(cfg.input_dirs)
    )

    kept: List[Tuple[Dict[str, Any], Path]] = []
    dropped = 0

    for path in files:
        try:
            rec = load_json(path)
        except Exception as e:
            logger.warning("Skipping unreadable JSON: %s | %s", path, repr(e))
            continue

        drop, _reasons = should_drop(rec)
        if drop:
            dropped += 1
            continue

        q = str(rec.get("question", "")).strip()
        if not q:
            dropped += 1
            continue

        kept.append((rec, path))

    logger.info("Records kept: %d | dropped: %d", len(kept), dropped)
    if not kept:
        logger.warning("No records passed the filters. Nothing to ingest.")
        return

    # 2) Optional concat JSONL (post-filter)
    if cfg.save_concat_jsonl:
        cfg.save_concat_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with cfg.save_concat_jsonl.open("w", encoding="utf-8") as f:
            for rec, path in kept:
                out = dict(rec)
                out["_meta"] = {"source_path": str(path)}
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
        logger.info("Saved concatenated JSONL → %s", cfg.save_concat_jsonl)

    # 3) Create / validate collection (need dense vector size)
    test_vec = dense_embed_questions(
        dense_model, [str(kept[0][0]["question"])], batch_size=1
    )[0]
    dense_size = len(test_vec)
    ensure_collection(
        qclient,
        cfg.collection_name,
        dense_size=dense_size,
        overwrite=cfg.overwrite_collection,
    )

    # 4) Embed + upsert in batches
    ids_batch: List[str] = []
    dense_batch: List[List[float]] = []
    sparse_batch: List[qmodels.SparseVector] = []
    payload_batch: List[Dict[str, Any]] = []

    def flush():
        if not ids_batch:
            return
        upsert_points(
            qclient=qclient,
            collection=cfg.collection_name,
            ids=ids_batch,
            dense_vecs=dense_batch,
            sparse_vecs=sparse_batch,
            payloads=payload_batch,
        )
        logger.info("Upserted %d points into '%s'", len(ids_batch), cfg.collection_name)
        ids_batch.clear()
        dense_batch.clear()
        sparse_batch.clear()
        payload_batch.clear()

    # Work buffers for dense embedding
    q_texts: List[str] = []
    recs: List[Dict[str, Any]] = []
    paths: List[Path] = []
    sparse_texts: List[str] = []

    def flush_embed_and_queue():
        if not q_texts:
            return

        # Dense: question only
        dense_vecs = dense_embed_questions(
            dense_model, q_texts, batch_size=cfg.dense_batch_size
        )

        # Sparse: question + key_terms
        sparse_vecs_raw = list(sparse_model.embed(sparse_texts))
        sparse_vecs = [
            qmodels.SparseVector(indices=sv.indices.tolist(), values=sv.values.tolist())
            for sv in sparse_vecs_raw
        ]

        for rec, path, dvec, svec, st in zip(
            recs, paths, dense_vecs, sparse_vecs, sparse_texts
        ):
            ids_batch.append(stable_point_id(rec))
            dense_batch.append(dvec)
            sparse_batch.append(svec)
            payload_batch.append(make_payload(rec, path, sparse_text=st))

            if len(ids_batch) >= cfg.qdrant_upsert_batch:
                flush()

        q_texts.clear()
        recs.clear()
        paths.clear()
        sparse_texts.clear()

    for rec, path in kept:
        question = str(rec.get("question", "")).strip()
        key_terms = rec.get("key_terms", [])
        if not isinstance(key_terms, list):
            key_terms = []

        q_texts.append(question)
        recs.append(rec)
        paths.append(path)
        sparse_texts.append(build_sparse_text(question, key_terms))

        if len(q_texts) >= cfg.dense_batch_size:
            flush_embed_and_queue()

    flush_embed_and_queue()
    flush()

    logger.info("Done. Total ingested: %d", len(kept))


# ── Entry point: choose variables here ────────────────────────────────────────
if __name__ == "__main__":
    """
    Expected .env:
      QDRANT_URL=http://localhost:6333   (or cloud URL)
      QDRANT_API_KEY=...                (optional)

    Dense model:
      - Default: intfloat/multilingual-e5-small (fast, multilingual, strong PT)
      - Alternative: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (also fast)

    Retrieval usage later:
      - Query dense vector: encode("query: ...") with same model, normalize_embeddings=True
      - Query sparse vector: sparse_hash_vector(question + key_terms, dim=sparse_dim)
    """

    INPUT_DIRS = [
        Path("../artifacts/chat-19012021-20022026/1-kb_threads_high"),
        Path("../artifacts/chat-19012021-20022026/1-kb_threads_medium"),
    ]

    config = IngestConfig(
        input_dirs=INPUT_DIRS,
        collection_name=os.getenv("QDRANT_COLLECTION", "habitantes_chat_kb_hybrid_2"),
        dense_model_name=os.getenv("DENSE_MODEL", "intfloat/multilingual-e5-large"),
        dense_batch_size=int(os.getenv("DENSE_BATCH", "64")),
        sparse_model_name=os.getenv("SPARSE_MODEL", "Qdrant/bm25"),
        overwrite_collection=False,
        qdrant_upsert_batch=int(os.getenv("QDRANT_UPSERT_BATCH", "128")),
        save_concat_jsonl=Path("../artifacts/concat/filtered_concat.jsonl"),
    )

    run_ingest(config)
