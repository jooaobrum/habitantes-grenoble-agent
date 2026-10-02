"""Opt-out list, erasure + rebuild, retention and the author-free check for the
Suggestion pipeline. LLMs are mocked at the HTTP layer; Qdrant is in-memory."""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from habitantes.config import SuggestionsConfig
from ingestion.config import JevConfig, MentionExtractionConfig
from ingestion.erase import erase_user_data
from ingestion.pipeline import cleanup_expired_artifacts
from ingestion.suggestions.build import run_suggestions_builder
from ingestion.suggestions.exclusions import load_exclusions
from ingestion.suggestions.mentions import MENTIONS_FILENAME, run_mentions_builder
from ingestion.suggestions.privacy import find_pii_leaks
from ingestion.suggestions.suggestions import SUGGESTIONS_FILENAME
from ingestion.preprocess.qa_pairs import extract_qa_pairs  # noqa: F401

os.environ.setdefault("OPENROUTER_API_KEY", "test")

COLLECTION = "suggestions_privacy_test"
AUTHOR_A = "Mariana Silva"
AUTHOR_B = "Bruno Costa"
PHONE = "+33 6 12 34 56 78"
CHAT_LINES = [
    ("[01/03/25, 10:00:00]", AUTHOR_B, "bom dia gente"),
    ("[01/03/25, 10:01:00]", AUTHOR_A, f"Adorei a Padaria Brasil, tel {PHONE}"),
    (
        "[01/03/25, 10:02:00]",
        AUTHOR_B,
        "O Mercado Tropical e otimo, fala com Mariana Silva",
    ),
    ("[01/03/25, 10:03:00]", "Carla Dias", "Recomendo o Dentista Alpes"),
]


class Emb:
    def dense(self, texts):
        return [np.ones(4).tolist() for _ in texts]

    def sparse(self, texts):
        return [qmodels.SparseVector(indices=[0], values=[1.0]) for _ in texts]


def _classified(raw: Path, out: Path) -> Path:
    rows = []
    for line in raw.read_text(encoding="utf-8").splitlines():
        stamp, rest = line[1:19], line[21:]
        user, _, msg = rest.partition(": ")
        rows.append(
            (pd.to_datetime(stamp, format="%d/%m/%y, %H:%M:%S"), user, msg, "statement")
        )
    p = out / "classified.csv"
    pd.DataFrame(rows, columns=["timestamp", "user", "message", "msg_type"]).to_csv(
        p, index=False
    )
    return p


def _mention(name, kind, ctx):
    return {
        "name": name,
        "kind": kind,
        "polarity": "positive",
        "items": [],
        "context": ctx,
        "date": "2025-03-01",
        "community_business": False,
    }


def _extraction_llm(request):
    """Echo a Mention per business named in the (pseudonymised) window text."""
    text = json.loads(request.content)["messages"][0]["content"]
    found = []
    if "Padaria Brasil" in text:
        found.append(_mention("Padaria Brasil", "Markets & Groceries", "Boa padaria."))
    if "Mercado Tropical" in text:
        found.append(
            _mention("Mercado Tropical", "Markets & Groceries", "Bom mercado.")
        )
    if "Dentista Alpes" in text:
        found.append(_mention("Dentista Alpes", "Dentists", "Bom dentista."))
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps({"mentions": found})}}]},
    )


def _merge_llm(request):
    text = json.loads(request.content)["messages"][0]["content"]
    content = {"groups": []} if "Agrupe" in text else {"label": "Grupo", "lines": {}}
    return httpx.Response(
        200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
    )


def _jev(request):
    return httpx.Response(200, json={"answers": {"has_suggestion": {"noul": 0.9}}})


def _chat(tmp_path: Path):
    data = tmp_path / "data"
    art = tmp_path / "artifacts"
    chat_dir = art / "chat"
    data.mkdir()
    chat_dir.mkdir(parents=True)
    raw = data / "chat.txt"
    raw.write_text(
        "".join(f"{ts} {u}: {m}\n" for ts, u, m in CHAT_LINES), encoding="utf-8"
    )
    return data, art, chat_dir, raw


def _rebuild(raw, chat_dir, client, exclusions=None):
    """mentions + suggestions pipelines over the (possibly redacted) raw export."""

    async def go():
        jc = httpx.AsyncClient(transport=httpx.MockTransport(_jev))
        lc = httpx.AsyncClient(transport=httpx.MockTransport(_extraction_llm))
        mc = httpx.AsyncClient(transport=httpx.MockTransport(_merge_llm))
        try:
            await run_mentions_builder(
                _classified(raw, chat_dir),
                chat_dir,
                3,
                JevConfig(max_retries=1, retry_base_sleep_s=0),
                SuggestionsConfig(),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                jev_client=jc,
                llm_client=lc,
            )
            return await run_suggestions_builder(
                chat_dir / MENTIONS_FILENAME,
                chat_dir,
                SuggestionsConfig(collection_name=COLLECTION),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                qclient=client,
                llm_client=mc,
                dense_embed=Emb().dense,
                sparse_embed=Emb().sparse,
                exclusions_path=exclusions,
            )
        finally:
            for c in (jc, lc, mc):
                await c.aclose()

    return asyncio.run(go())


def _payloads(client):
    try:
        pts, _ = client.scroll(COLLECTION, limit=100, with_payload=True)
    except Exception:
        return []
    return [p.payload for p in pts]


def _member_names(client):
    return {m["name"] for p in _payloads(client) for m in p["members"]}


def _all_text(chat_dir, client):
    parts = [
        (chat_dir / f).read_text(encoding="utf-8")
        for f in (MENTIONS_FILENAME, SUGGESTIONS_FILENAME)
        if (chat_dir / f).exists()
    ]
    return "\n".join(parts + [json.dumps(_payloads(client), ensure_ascii=False)])


# ── exclusion list ───────────────────────────────────────────────────────────
def test_exclusion_list_removes_business_on_every_rebuild(tmp_path):
    data, art, chat_dir, raw = _chat(tmp_path)
    client = QdrantClient(":memory:")
    _rebuild(raw, chat_dir, client)
    assert "Padaria Brasil" in _member_names(client)

    excl = tmp_path / "exclusions.txt"
    excl.write_text("# opt-outs\n\n  padaria  BRASIL!  \n", encoding="utf-8")
    assert load_exclusions(excl) == {"padaria brasil"}

    _rebuild(raw, chat_dir, client, exclusions=excl)
    names = _member_names(client)
    assert "Padaria Brasil" not in names and "Mercado Tropical" in names
    stored = (chat_dir / SUGGESTIONS_FILENAME).read_text(encoding="utf-8")
    assert "Padaria Brasil" not in stored

    # rebuilding again (from the stored file) keeps it out
    async def again():
        lc = httpx.AsyncClient(transport=httpx.MockTransport(_merge_llm))
        try:
            return await run_suggestions_builder(
                chat_dir / MENTIONS_FILENAME,
                chat_dir,
                SuggestionsConfig(collection_name=COLLECTION),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                qclient=client,
                llm_client=lc,
                dense_embed=Emb().dense,
                sparse_embed=Emb().sparse,
                from_suggestions_file=True,
                exclusions_path=excl,
            )
        finally:
            await lc.aclose()

    asyncio.run(again())
    assert "Padaria Brasil" not in _member_names(client)


def test_exclusion_list_missing_file_excludes_nothing(tmp_path):
    assert load_exclusions(tmp_path / "nope.txt") == set()


def test_exclusion_added_after_a_stored_file_applies_on_stored_rebuild(tmp_path):
    data, art, chat_dir, raw = _chat(tmp_path)
    client = QdrantClient(":memory:")
    _rebuild(raw, chat_dir, client)
    excl = tmp_path / "exclusions.txt"
    excl.write_text("Mercado Tropical\n", encoding="utf-8")

    async def go():
        lc = httpx.AsyncClient(transport=httpx.MockTransport(_merge_llm))
        try:
            await run_suggestions_builder(
                chat_dir / MENTIONS_FILENAME,
                chat_dir,
                SuggestionsConfig(collection_name=COLLECTION),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                qclient=client,
                llm_client=lc,
                dense_embed=Emb().dense,
                sparse_embed=Emb().sparse,
                from_suggestions_file=True,
                exclusions_path=excl,
            )
        finally:
            await lc.aclose()

    asyncio.run(go())
    assert "Mercado Tropical" not in _member_names(client)
    assert "Padaria Brasil" in _member_names(client)


# ── erasure + rebuild ────────────────────────────────────────────────────────
def test_erasure_then_rebuild_leaves_no_mention_from_member(tmp_path):
    data, art, chat_dir, raw = _chat(tmp_path)
    client = QdrantClient(":memory:")
    _rebuild(raw, chat_dir, client)
    assert "Padaria Brasil" in _member_names(client)

    rebuilt = []
    report = erase_user_data(
        [AUTHOR_A],
        data,
        art,
        "qa_kb",
        dry_run=False,
        rebuild_suggestions=lambda: rebuilt.append(_rebuild(raw, chat_dir, client)),
    )
    assert report["suggestion_files_removed"] == 2
    assert len(rebuilt) == 1  # rebuild ran after the redaction
    names = _member_names(client)
    assert "Padaria Brasil" not in names  # only AUTHOR_A mentioned it
    assert {"Mercado Tropical", "Dentista Alpes"} <= names
    assert "Padaria Brasil" not in (chat_dir / MENTIONS_FILENAME).read_text(
        encoding="utf-8"
    )


def test_erasure_dry_run_keeps_derived_files_and_does_not_rebuild(tmp_path):
    data, art, chat_dir, raw = _chat(tmp_path)
    (chat_dir / MENTIONS_FILENAME).write_text("{}\n", encoding="utf-8")
    (chat_dir / SUGGESTIONS_FILENAME).write_text("{}\n", encoding="utf-8")
    called = []
    report = erase_user_data(
        [AUTHOR_A],
        data,
        art,
        "qa_kb",
        dry_run=True,
        rebuild_suggestions=lambda: called.append(1),
    )
    assert report["suggestion_files_removed"] == 2
    assert (chat_dir / MENTIONS_FILENAME).exists() and not called


# ── retention ────────────────────────────────────────────────────────────────
def test_retention_deletes_expired_mentions_and_suggestions_files(tmp_path):
    data, art, chat_dir, _ = _chat(tmp_path)
    old = time.time() - 100 * 86400
    stale = [chat_dir / MENTIONS_FILENAME, chat_dir / SUGGESTIONS_FILENAME]
    for f in stale:
        f.write_text("{}\n", encoding="utf-8")
        os.utime(f, (old, old))
    fresh_dir = art / "fresh"
    fresh_dir.mkdir()
    fresh = fresh_dir / MENTIONS_FILENAME
    fresh.write_text("{}\n", encoding="utf-8")

    cleanup_expired_artifacts(data, art, retention_days=90)

    assert not any(f.exists() for f in stale)
    assert fresh.exists()


# ── author-free check ────────────────────────────────────────────────────────
def test_nothing_derived_contains_author_member_tag_or_phone(tmp_path):
    data, art, chat_dir, raw = _chat(tmp_path)
    client = QdrantClient(":memory:")
    _rebuild(raw, chat_dir, client)
    text = _all_text(chat_dir, client)
    assert text.strip() and "Padaria Brasil" in text
    assert find_pii_leaks(text, [AUTHOR_A, AUTHOR_B, "Carla Dias"]) == []


def test_pii_check_detects_names_tags_and_phones():
    leaks = find_pii_leaks(f"fala com {AUTHOR_A}, M3 disse, ligue {PHONE}", [AUTHOR_A])
    assert len(leaks) == 3
    assert find_pii_leaks("Grand Frais tem ótimas frutas", [AUTHOR_A]) == []


def test_suggestions_pipeline_runs_retention_cleanup(monkeypatch):
    import asyncio

    import ingestion.suggestions.pipeline as pl

    calls = []

    async def fake_builder(**_):
        return 7

    monkeypatch.setattr(pl, "run_suggestions_builder", fake_builder)
    monkeypatch.setattr(pl, "cleanup_expired_artifacts", lambda **kw: calls.append(kw))
    assert asyncio.run(pl.run_suggestions_pipeline()) == 7
    assert len(calls) == 1
    assert calls[0]["retention_days"] == pl.settings.artifacts_retention_days
