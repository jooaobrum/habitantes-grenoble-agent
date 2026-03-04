import math
import re
import unicodedata
from datetime import datetime
from qdrant_client.http import models as qmodels

_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ']+")
_ANCHOR_BONUS = 0.05
_RERANK_TOP_K = 40  # Top candidates to rerank with anchors


def _calculate_date_decay(date_str: str | None) -> float:
    """Calculate a decay factor (0.0 to 1.0) based on document age.

    Formula: exp(-days_old * lambda)
    Lambda 0.0005 means:
      - 0 days: 1.0
      - 365 days (~1yr): 0.83
      - 1000 days (~2.7yrs): 0.60
      - 2000 days (~5.4yrs): 0.36
    """
    if not date_str:
        return 1.0
    try:
        # Handle formats like "2025-08-14 17:47:37" or ISO
        dt = None
        # Normalization: take only the first 19 chars (YYYY-MM-DD HH:MM:SS)
        clean_date = date_str.replace("T", " ").split(".")[0][:19]
        fmt = "%Y-%m-%d %H:%M:%S"
        try:
            dt = datetime.strptime(clean_date, fmt)
        except ValueError:
            return 1.0

        now = datetime.now()
        days_old = (now - dt).days
        if days_old < 0:
            return 1.0

        # lambda = 0.0005
        return math.exp(-days_old * 0.0005)
    except Exception:
        return 1.0


# ── Category filter (OR logic for top-2) ─────────────────────────────────────


def _category_filter(categories: list[str] | None) -> qmodels.Filter | None:
    if not categories:
        return None
    conditions = [
        qmodels.FieldCondition(key="category", match=qmodels.MatchValue(value=cat))
        for cat in categories
    ]
    if len(conditions) == 1:
        return qmodels.Filter(must=conditions)
    return qmodels.Filter(should=conditions)  # OR across top-2 categories


# ── Text normalisation (D) ────────────────────────────────────────────────────


def strip_accents(text: str) -> str:
    """Lowercase + strip diacritics for accent-insensitive matching."""
    return (
        unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    )


# ── Domain key-term extraction + BM25 enrichment (C) ─────────────────────────


def extract_key_terms(query: str) -> list[str]:
    """Return glossary terms found in the query (greedy, longest-first).

    Matching is done on the normalized (lowercase, no accents) query so that
    'Récépissé', 'recepisse', 'RECEPISSE' all resolve to the same term.
    """
    from habitantes.domain.glossary import TERM_KEYS

    q_norm = strip_accents(query)
    found: list[str] = []
    covered: set[int] = set()

    for term in TERM_KEYS:  # longest first → greedy, no sub-term double-count
        idx = q_norm.find(term)
        if idx != -1 and idx not in covered:
            found.append(term)
            covered.update(range(idx, idx + len(term)))

    return found


def enrich_bm25_input(text_normalized: str) -> str:
    """Append matched domain terms to a ALREADY NORMALIZED text to amplify TF.

    Repeating terms raises TF and pushes their BM25 weight up.
    """
    key_terms = extract_key_terms(text_normalized)
    if not key_terms:
        return text_normalized
    return f"{text_normalized} {' '.join(key_terms)}"


# ── Anchor rerank (PT + FR stopwords) ────────────────────────────────────────

_PT_STOPWORDS = {
    "a",
    "o",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "e",
    "ou",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "por",
    "para",
    "com",
    "sem",
    "que",
    "como",
    "onde",
    "quando",
    "qual",
    "quais",
    "quem",
    "porque",
    "pq",
    "pra",
    "pro",
    "isso",
    "essa",
    "esse",
    "aquele",
    "aquela",
    "aqui",
    "ali",
    "muito",
    "mais",
    "menos",
    "também",
    "tbm",
    "já",
    "não",
    "sim",
    "eu",
    "vc",
    "vcs",
    "vocês",
}
_FR_STOPWORDS = {
    "le",
    "la",
    "les",
    "un",
    "une",
    "des",
    "du",
    "de",
    "d",
    "et",
    "en",
    "à",
    "a",
    "au",
    "aux",
    "pour",
    "par",
    "sur",
    "dans",
    "avec",
    "sans",
    "ce",
    "cet",
    "cette",
    "ces",
    "qui",
    "que",
    "quoi",
    "dont",
    "où",
    "mais",
    "ou",
    "donc",
    "or",
    "ni",
    "ne",
    "pas",
    "plus",
    "moins",
    "très",
    "tres",
    "se",
    "sa",
    "son",
    "ses",
    "leur",
    "leurs",
    "mon",
    "ma",
    "mes",
    "ton",
    "ta",
    "tes",
    "nous",
    "vous",
    "ils",
    "elles",
    "je",
    "tu",
    "il",
    "elle",
    "on",
    "y",
    "lui",
    "leur",
}


def _extract_anchors(query: str, min_len: int = 4) -> list[str]:
    out, seen = [], set()
    for tok in _TOKEN_RE.findall(query):
        t = tok.lower()
        if len(t) < min_len or t in _PT_STOPWORDS or t in _FR_STOPWORDS or t in seen:
            continue
        out.append(t)
        seen.add(t)
    return out


def _rerank_with_anchors(query: str, points: list) -> list:
    anchors = _extract_anchors(query)
    if not anchors:
        return points

    head, tail = points[:_RERANK_TOP_K], points[_RERANK_TOP_K:]
    denom = max(1, len(anchors))

    anchors_norm = [strip_accents(a) for a in anchors]  # D: normalize anchors

    rescored = []
    for sp in head:
        pl = sp.payload or {}
        blob_norm = strip_accents(
            " ".join(
                str(pl.get(k) or "")
                for k in ("question", "answer", "category", "subcategory")
            )
        )  # D: normalize blob
        hits = sum(1 for a in anchors_norm if a in blob_norm)
        rescored.append((float(sp.score) + _ANCHOR_BONUS * (hits / denom), sp))

    rescored.sort(key=lambda x: x[0], reverse=True)
    return [sp for _, sp in rescored] + tail


# ── Thread-level deduplication ───────────────────────────────────────────────


def _deduplicate_by_thread(points: list) -> list:
    """Keep only the highest-scoring chunk per thread_id.

    Preserves the original rank order so context_precision is not disturbed.
    Falls back to point.id when thread_id is absent.
    """
    seen: set[str] = set()
    unique = []
    for p in points:
        tid = str((p.payload or {}).get("thread_id", p.id))
        if tid not in seen:
            seen.add(tid)
            unique.append(p)
    return unique
