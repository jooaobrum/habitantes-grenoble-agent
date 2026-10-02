"""Ingestion seam: classified chat CSV -> author-free Mentions file.

Jev (decisions endpoint) and the extraction LLM (chat completions) are mocked at
the HTTP layer with httpx.MockTransport: no network.
"""

import asyncio
import json
import os

import httpx
import pandas as pd

from ingestion.config import JevConfig, MentionExtractionConfig
from ingestion.preprocess.qa_pairs import extract_qa_pairs
from ingestion.suggestions.mentions import (
    MENTIONS_FILENAME,
    read_mentions,
    run_mentions_builder,
)
from ingestion.suggestions.windows import build_windows
from habitantes.config import SuggestionsConfig

os.environ.setdefault("OPENROUTER_API_KEY", "test")

SECRET_NAME = "Mariana Silva"
PHONE = "+33 6 12 34 56 78"


def _rows():
    t = pd.Timestamp("2025-03-01 10:00:00")
    msgs = [
        ("Bruno Costa", "bom dia gente", "statement"),
        (
            SECRET_NAME,
            f"Comprei na Padaria Brasil e adorei a massa de pastel, tel {PHONE}",
            "statement",
        ),
        ("Bruno Costa", "super recomendo mesmo", "statement"),
        # new thread (gap > 3h)
        ("Ana Lima", "alguém indica dentista?", "question"),
        ("Bruno Costa", "nada a ver", "statement"),
    ]
    out = []
    for i, (u, m, ty) in enumerate(msgs):
        gap = 5 * 3600 * (i >= 3)
        out.append((t + pd.Timedelta(minutes=i) + pd.Timedelta(seconds=gap), u, m, ty))
    return pd.DataFrame(out, columns=["timestamp", "user", "message", "msg_type"])


def _csv(tmp_path):
    p = tmp_path / "classified.csv"
    _rows().to_csv(p, index=False)
    return p


def _llm_content():
    return {
        "mentions": [
            {
                "name": "Padaria Brasil",
                "kind": "Markets & Groceries",
                "polarity": "positive",
                "items": ["massa de pastel"],
                "context": "Boa para massa de pastel.",
                "date": "2025-03-01",
                "community_business": False,
                "author": "M1",  # an unknown key must never reach the file
            }
        ]
    }


def _run(tmp_path, jev_handler, llm_handler, cfg=None):
    jc = httpx.AsyncClient(transport=httpx.MockTransport(jev_handler))
    lc = httpx.AsyncClient(transport=httpx.MockTransport(llm_handler))

    async def go():
        try:
            return await run_mentions_builder(
                _csv(tmp_path),
                tmp_path,
                3,
                JevConfig(max_retries=1, retry_base_sleep_s=0),
                cfg or SuggestionsConfig(),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                jev_client=jc,
                llm_client=lc,
            )
        finally:
            await jc.aclose()
            await lc.aclose()

    return asyncio.run(go())


def _jev_yes(request):
    return httpx.Response(200, json={"answers": {"has_suggestion": {"noul": 0.99}}})


def _llm_ok(seen):
    def handler(request):
        seen.append(json.loads(request.content)["messages"][0]["content"])
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(_llm_content())}}]},
        )

    return handler


def test_plain_statement_is_captured_and_output_is_author_free(tmp_path):
    seen: list[str] = []
    path = _run(tmp_path, _jev_yes, _llm_ok(seen))

    mentions = read_mentions(path)
    assert path.name == MENTIONS_FILENAME
    assert mentions and mentions[0].name == "Padaria Brasil"
    assert mentions[0].kind.value == "Markets & Groceries"
    assert mentions[0].items == ["massa de pastel"]

    raw = path.read_text(encoding="utf-8")
    assert "author" not in raw
    for secret in (SECRET_NAME, "Bruno", "Ana Lima", "33 6 12", "12 34 56"):
        assert secret not in raw

    # Authors are pseudonymised and phones scrubbed before the LLM sees text.
    sent = "\n".join(seen)
    assert "M1:" in sent and "M2:" in sent
    for secret in (SECRET_NAME, "Bruno", "Ana Lima", "12 34 56"):
        assert secret not in sent


def test_jev_no_means_no_extraction(tmp_path):
    def jev_no(request):
        return httpx.Response(200, json={"answers": {"has_suggestion": {"noul": 0.1}}})

    seen: list[str] = []
    path = _run(tmp_path, jev_no, _llm_ok(seen))
    assert read_mentions(path) == []
    assert seen == []


def test_jev_failure_skips_window(tmp_path, caplog):
    def jev_fail(request):
        return httpx.Response(500)

    seen: list[str] = []
    path = _run(tmp_path, jev_fail, _llm_ok(seen))
    assert read_mentions(path) == []
    assert seen == []
    assert "Jev" in caplog.text


def test_extraction_failure_is_logged_not_fatal(tmp_path):
    path = _run(tmp_path, _jev_yes, lambda r: httpx.Response(500))
    assert read_mentions(path) == []


def test_windows_merge_and_respect_thread_boundary():
    df = _rows()
    windows = build_windows(df, 3, before=5, after_request=15, after_other=5)
    # two threads -> two windows (overlaps merged, nothing crosses the gap)
    assert len(windows) == 2
    assert [len(w.messages) for w in windows] == [3, 2]
    assert windows[0].thread_id != windows[1].thread_id


def test_window_sizes_come_from_configuration():
    t = pd.Timestamp("2025-03-01 10:00:00")
    rows = [
        (
            t + pd.Timedelta(minutes=i),
            "u",
            "nada" if i != 5 else "gostei muito",
            "statement",
        )
        for i in range(12)
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "user", "message", "msg_type"])
    (w,) = build_windows(df, 3, before=1, after_request=15, after_other=2)
    assert len(w.messages) == 4  # indices 4..7


def test_qa_outputs_unchanged(tmp_path):
    csv = _csv(tmp_path)
    before_csv = csv.read_bytes()

    async def qa():
        return await extract_qa_pairs(csv, 3, 2, 5, 50, 20)

    qa_before = asyncio.run(qa())
    seen: list[str] = []
    _run(tmp_path, _jev_yes, _llm_ok(seen))
    qa_after = asyncio.run(qa())

    assert csv.read_bytes() == before_csv
    assert qa_after == qa_before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "classified.csv",
        MENTIONS_FILENAME,
    ]
