"""Candidate windows for the Suggestions pipeline.

A broad lexicon marks trigger messages (whatever their question/answer label);
each trigger opens a window of neighbouring messages inside its Thread. Windows
that overlap are merged; a window never crosses a Thread boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from ingestion.preprocess.qa_pairs import detect_threads

# Request phrases: someone asks who/where to go to -> longer forward window.
REQUEST_PATTERNS = [
    r"algu[eé]m (?:sabe|conhece|indica|recomenda|tem)\b",
    r"\bquem (?:indica|recomenda|conhece|tem)\b",
    r"\bindica[cç][aãoõ]\w*\b",
    r"\bonde (?:eu )?(?:compro|encontro|acho|consigo|comprar|encontrar|achar)\b",
    r"\b(?:procuro|estou procurando|t[oô] procurando|preciso de um[a]?)\b",
    r"\brecomenda[cç][oõã]\w*\b",
    r"\bsugest[aãoõ]\w*\b",
]

# Every other trigger group: opens a shorter forward window.
OTHER_PATTERNS = [
    # pointers to a place
    r"\b(?:comprei|compro|fui|vou|ia|costumo ir|vamos|fomos) (?:n[oa]s?|em|l[aá])\b",
    r"\btem (?:uma?|o|a) (?:loja|mercado|padaria|restaurante|dentista|m[eé]dic[oa]|cabeleireir[oa]|barbearia|sal[aã]o)\b",
    r"\b(?:carrefour|leclerc|lidl|aldi|grand frais|auchan|intermarch[eé]|monoprix|picard|casino|biocoop|decathlon|action|primark|ikea)\b",
    # first-person opinions
    r"\b(?:eu uso|gostei|adorei|amei|[eé] a melhor|[eé] o melhor|vale a pena|recomendo|super recomendo|curti)\b",
    # links: maps, social handles, booking sites
    r"(?:maps\.app\.goo\.gl|google\.[a-z.]+/maps|goo\.gl/maps|instagram\.com|doctolib\.|booking\.com|tripadvisor\.|thefork\.|ubereats\.|deliveroo\.)",
    r"(?<!\w)@[\w.]{3,}",
    # recommendation words
    r"\b(?:recomenda\w*|indico|indicam|restaurante|padaria|cabeleireir[oa]|dentista|tradutor[a]?)\b",
    # negative phrases
    r"\b(?:n[aã]o recomendo|evitem|evitar|p[eé]ssim[oa]|horr[ií]vel|decepcion\w+|nunca mais)\b",
]

_REQUEST_RE = re.compile("|".join(REQUEST_PATTERNS), re.IGNORECASE)
_OTHER_RE = re.compile("|".join(OTHER_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class Window:
    thread_id: int
    messages: List[Dict[str, Any]]  # each: user, timestamp, message


def is_request(text: str) -> bool:
    return bool(_REQUEST_RE.search(text or ""))


def is_trigger(text: str) -> bool:
    return is_request(text) or bool(_OTHER_RE.search(text or ""))


def thread_windows(
    msgs: List[Dict[str, Any]],
    before: int,
    after_request: int,
    after_other: int,
) -> List[tuple[int, int]]:
    """(start, end) inclusive index ranges inside one Thread, merged on overlap."""
    spans: List[tuple[int, int]] = []
    n = len(msgs)
    for i, m in enumerate(msgs):
        text = str(m.get("message", ""))
        if is_request(text):
            after = after_request
        elif is_trigger(text):
            after = after_other
        else:
            continue
        spans.append((max(0, i - before), min(n - 1, i + after)))
    merged: List[tuple[int, int]] = []
    for s, e in spans:  # spans are already ordered by start
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def build_windows(
    df: pd.DataFrame,
    thread_gap_h: int,
    before: int,
    after_request: int,
    after_other: int,
) -> List[Window]:
    """Windows for every Thread of a classified chat (Thread splitting reused)."""
    windows: List[Window] = []
    for tid, thread_df in enumerate(detect_threads(df, thread_gap_h)):
        msgs = thread_df.to_dict(orient="records")
        for s, e in thread_windows(msgs, before, after_request, after_other):
            windows.append(Window(tid, msgs[s : e + 1]))
    return windows
