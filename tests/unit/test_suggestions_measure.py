"""Scoring of Mention extraction against a tiny hand-made labelled fixture.

No labels are real: the fixture exists only to pin the measurement logic.
"""

import asyncio
import json
from datetime import date

import pandas as pd
import pytest

from habitantes.domain.suggestions import Kind
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.labelling import draw_sample, write_sample
from ingestion.suggestions.measure import (
    format_report,
    load_labelled,
    measure,
    names_match,
)

WINDOWS = dict(before=1, after_request=2, after_other=1)


def _msgs(texts):
    return [
        {"idx": i, "user": "M1", "timestamp": "2025-03-01 10:00:00", "message": t}
        for i, t in enumerate(texts)
    ]


def _mention(name, kind):
    return Mention(
        name=name,
        kind=kind,
        polarity="positive",
        context="boa",
        date=date(2025, 3, 1),
    )


FIXTURE = [
    {
        "thread_id": 0,
        "messages": _msgs(
            [
                "bom dia",
                "alguem indica um dentista?",
                "ok",
                "eu vou no Dr Silva",
                "cinco",
                "seis",
                "sete",
                "oito",
                "Comprei no Leclerc e adorei",
            ]
        ),
        "suggestions": [
            {
                "name": "Dr Silva",
                "kind": "Dentists",
                "polarity": "positive",
                "evidence": [3],
            },
            # inside the request window (idx 0..3) -> covered but never extracted
            {
                "name": "Clinica Sorriso",
                "kind": "Dentists",
                "polarity": "positive",
                "evidence": [2],
            },
            # far from any trigger -> outside windows
            {
                "name": "Padaria X",
                "kind": "Shops",
                "polarity": "positive",
                "evidence": [6],
            },
            {
                "name": "Leclerc",
                "kind": "Markets & Groceries",
                "polarity": "positive",
                "evidence": [8],
            },
        ],
    }
]


def test_per_kind_coverage_recall_and_wrong():
    async def extractor(window):
        text = " ".join(m["message"] for m in window.messages)
        out = []
        if "Dr Silva" in text:
            out.append(_mention("Dr. Silva", Kind.DENTISTS))
            out.append(_mention("Invented Clinic", Kind.DENTISTS))  # wrong
        if "Leclerc" in text:
            out.append(_mention("E.Leclerc", Kind.MARKETS_AND_GROCERIES))
        return out

    r = asyncio.run(measure(FIXTURE, extractor, **WINDOWS))
    d = r.per_kind["Dentists"]
    assert (d.labelled, d.covered, d.recalled, d.extracted, d.wrong) == (2, 2, 1, 2, 1)
    s = r.per_kind["Shops"]
    assert (s.labelled, s.covered, s.recalled) == (1, 0, 0)
    m = r.per_kind["Markets & Groceries"]
    assert (m.labelled, m.covered, m.recalled, m.wrong) == (1, 1, 1, 0)
    t = r.total()
    assert (t.labelled, t.covered, t.recalled, t.wrong) == (4, 3, 2, 1)
    assert [u["name"] for u in r.uncovered] == ["Padaria X"]
    assert {x["name"] for x in r.missed} == {"Clinica Sorriso", "Padaria X"}
    assert r.wrong_mentions[0]["name"] == "Invented Clinic"
    assert "TOTAL" in format_report(r)


def test_kind_mismatch_is_wrong_and_missed():
    async def extractor(window):
        text = " ".join(m["message"] for m in window.messages)
        return [_mention("Leclerc", Kind.SHOPS)] if "Leclerc" in text else []

    r = asyncio.run(measure(FIXTURE, extractor, **WINDOWS))
    assert r.per_kind["Shops"].wrong == 1
    assert r.per_kind["Markets & Groceries"].recalled == 0


def test_label_without_evidence_rejected():
    bad = [
        {
            "thread_id": 1,
            "messages": _msgs(["a"]),
            "suggestions": [
                {"name": "X", "kind": "Shops", "polarity": "positive", "evidence": []}
            ],
        }
    ]

    async def none(window):
        return []

    with pytest.raises(ValueError, match="evidence"):
        asyncio.run(measure(bad, none, **WINDOWS))


def test_names_match_ignores_case_accents_and_containment():
    assert names_match("Pâtisserie Léa", "patisserie lea")
    assert names_match("Leclerc", "E.Leclerc Voreppe")
    assert not names_match("Lidl", "Aldi")


def test_draw_sample_is_seeded_and_empty_labels(tmp_path):
    rows = []
    for t in range(10):  # 10 threads, 4 messages each, 10h apart
        for i in range(4):
            rows.append(
                {
                    "timestamp": pd.Timestamp("2025-03-01")
                    + pd.Timedelta(hours=10 * t, minutes=i),
                    "user": f"user{i % 2}",
                    "message": f"msg {t}-{i}",
                }
            )
    df = pd.DataFrame(rows)
    a = draw_sample(df, thread_gap_h=3, n=4, seed=1)
    b = draw_sample(df, thread_gap_h=3, n=4, seed=1)
    assert a == b and len(a) == 4
    assert all(r["suggestions"] == [] for r in a)
    assert {m["user"] for r in a for m in r["messages"]} <= {"M1", "M2"}
    path = tmp_path / "s.jsonl"
    write_sample(a, path)
    assert load_labelled(path) == json.loads(json.dumps(a))
