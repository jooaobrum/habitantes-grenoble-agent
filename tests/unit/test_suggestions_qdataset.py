import asyncio
from datetime import date

import pandas as pd

from habitantes.domain.suggestions import Kind
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.qdataset import build_dataset, find_candidates


def _m(name, polarity="positive", kind=Kind.MARKETS_AND_GROCERIES, items=()):
    return Mention(
        name=name,
        kind=kind,
        polarity=polarity,
        items=list(items),
        context="x",
        date=date(2024, 1, 1),
        community_business=False,
    )


def _df():
    rows = [
        (
            "2024-01-01 10:00:00",
            "Ana",
            "Alguém indica onde comprar massa de pastel em Grenoble?",
        ),
        ("2024-01-01 10:05:00", "Bia", "Na Épicerie Tropical tem massa de pastel"),
        ("2024-01-01 10:06:00", "Caio", "Concordo, Épicerie Tropical é ótima"),
        (
            "2024-01-05 10:00:00",
            "Ana",
            "Alguém recomenda um dentista aqui em Grenoble?",
        ),
        ("2024-01-05 10:02:00", "Bia", "Não conheço nenhum, desculpa"),
    ]
    return pd.DataFrame(rows, columns=["timestamp", "user", "message"]).assign(
        timestamp=lambda d: pd.to_datetime(d["timestamp"])
    )


def test_dataset_keeps_requests_with_positive_replies_and_cleans_the_question():
    cands = find_candidates(_df(), thread_gap_h=12, after=5)
    assert len(cands) == 2

    async def extract(window):
        text = " ".join(m["message"] for m in window.messages)
        if "Épicerie" in text:
            return [
                _m("Épicerie Tropical", items=["massa de pastel"]),
                _m("Épicerie Tropical"),
                _m("Loja Ruim", polarity="negative"),
            ]
        return []

    async def rewrite(request, window):
        return "Onde comprar massa de pastel em Grenoble?"

    cases = asyncio.run(build_dataset(cands, extract, rewrite, n_requests=10))

    assert len(cases) == 1  # the dentist request got no positive reply
    c = cases[0]
    assert c["question"] == "Onde comprar massa de pastel em Grenoble?"
    assert c["kind"] == "Markets & Groceries"
    assert c["expected_suggestions"] == [
        {
            "name": "Épicerie Tropical",
            "kind": "Markets & Groceries",
            "thumbs_up": 2,
            "thumbs_down": 0,
            "items": ["massa de pastel"],
            "community_business": False,
        }
    ]  # the negative-only place is not an expected Suggestion
    assert c["status"] == "pseudo"


def test_judge_drops_suggestions_that_answer_a_different_question():
    cands = find_candidates(_df(), thread_gap_h=12, after=5)[:1]

    async def extract(window):
        return [_m("Épicerie Tropical"), _m("camptocamp.org")]

    async def rewrite(request, window):
        return "Onde comprar massa de pastel?"

    async def judge(request, window, names):
        return ["Épicerie Tropical"]

    cases = asyncio.run(build_dataset(cands, extract, rewrite, 5, judge=judge))
    assert [e["name"] for e in cases[0]["expected_suggestions"]] == [
        "Épicerie Tropical"
    ]

    async def not_a_request(request, window, names):
        return None

    assert (
        asyncio.run(build_dataset(cands, extract, rewrite, 5, judge=not_a_request))
        == []
    )
