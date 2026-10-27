import asyncio
from datetime import date

from habitantes.domain.suggestions import (
    KIND_SUBCATEGORIES,
    SUBCATEGORY_GUIDE,
    Kind,
    subcategory_guide_text,
    valid_subcategory,
)
from ingestion.suggestions.extract import (
    EXTRACTION_PROMPT,
    SUBCATEGORY_PROMPT,
    _RawMention,
    _to_mention,
)
from ingestion.suggestions.source_messages import index_messages, source_messages
from ingestion.suggestions.subcategory import (
    apply_subcategories,
    assign,
    build_group_records,
    build_prompt,
)


def test_vocabulary_is_consistent():
    for kind, names in KIND_SUBCATEGORIES.items():
        assert len(names) == len(set(names)) >= 2, kind
        assert [n for n, _ in SUBCATEGORY_GUIDE[kind]] == list(names)
        assert all(d for _, d in SUBCATEGORY_GUIDE[kind])  # every one is defined
        assert "Outros" not in names[:-1]  # the fallback, when present, comes last
    assert Kind.HOUSING not in KIND_SUBCATEGORIES  # too few groups to split
    assert valid_subcategory("Doctors", "Hospitais e Urgência")
    assert not valid_subcategory("Doctors", "Franceses")
    assert not valid_subcategory("Housing", "Outros")


def test_extraction_prompt_lists_every_subcategory_with_its_definition():
    assert "{subcategories}" in EXTRACTION_PROMPT
    for kind, guide in SUBCATEGORY_GUIDE.items():
        assert kind.value in SUBCATEGORY_PROMPT
        for name, definition in guide:
            assert f"- {name}: {definition}" in SUBCATEGORY_PROMPT


def _raw(**kw):
    base = dict(
        name="Natal",
        kind="Restaurants & Bars",
        polarity="positive",
        context="ótimo",
        date="2025-01-01",
    )
    return _RawMention(**{**base, **kw})


def test_extraction_keeps_a_valid_subcategory_and_drops_one_from_another_kind():
    ok = _to_mention(_raw(subcategory="Comida Brasileira"), date(2025, 1, 1))
    assert ok.subcategory == "Comida Brasileira"
    wrong = _to_mention(_raw(subcategory="Aéreo"), date(2025, 1, 1))
    assert wrong is not None and wrong.subcategory is None  # the Mention survives
    assert _to_mention(_raw(), date(2025, 1, 1)).subcategory is None
    assert (
        _to_mention(
            _raw(kind="Housing", subcategory="Outros"), date(2025, 1, 1)
        ).subcategory
        is None
    )


ROWS = [
    {"group": "Natal", "name": "Natal", "kind": "Restaurants & Bars", "items": ["açaí"], "context": "ótimo", "date": "2025-01-01"},
    {"group": "Natal", "name": "O Natal", "kind": "Restaurants & Bars", "items": ["coxinha"], "context": "bom", "date": "2025-02-01"},
    {"group": "FlixBus", "name": "FlixBus", "kind": "Transport", "items": [], "context": "barato", "date": "2025-01-05"},
    {"group": "Résidence X", "name": "Résidence X", "kind": "Housing", "items": [], "context": "ok", "date": "2025-01-06"},
]  # fmt: skip


def test_assign_uses_the_kind_vocabulary_and_skips_kinds_without_subcategories():
    seen = []

    async def chat(client, prompt, cfg, schema=None):
        seen.append(prompt)
        assert (
            schema
            and schema["schema"]["properties"]["r"]["items"]["properties"]["s"]["enum"]
        )
        if "Restaurants & Bars" in prompt:
            return {"r": [{"i": 0, "s": "Comida Brasileira"}]}
        return {"r": [{"i": 0, "s": "Invented"}]}  # not in the vocabulary -> ignored

    records = build_group_records(
        ROWS, {"Natal": {"messages": ["Fui no Natal, amei o açaí"]}}
    )
    subs = asyncio.run(assign(records, chat, None, None))
    assert subs == {"Natal": "Comida Brasileira", "FlixBus": None, "Résidence X": None}
    assert (
        len(seen) == 3
    )  # Restaurants, Transport (invalid answer) + its one retry; none for Housing
    assert "Comida Brasileira: " in seen[0] and "Fui no Natal, amei o açaí" in seen[0]
    out = apply_subcategories(ROWS, subs)
    assert [r["subcategory"] for r in out] == [
        "Comida Brasileira",
        "Comida Brasileira",
        None,
        None,
    ]
    assert all(set(a) <= set(b) for a, b in zip(ROWS, out))  # nothing else changes


def test_prompt_shows_the_kinds_definitions():
    p = build_prompt(
        "Transport",
        [{"group": "FlixBus", "items": [], "messages": [], "context": "barato"}],
    )
    assert subcategory_guide_text("Transport") in p and "FlixBus" in p


def test_source_messages_match_by_date_and_name_and_scrub_phones():
    chat = [
        {
            "timestamp": "2025-01-01 10:00:00",
            "message": "Fui no Natal e adorei, tel 06 12 34 56 78",
        },
        {"timestamp": "2025-01-01 11:00:00", "message": "Alguém conhece dentista?"},
        {"timestamp": "2025-01-02 09:00:00", "message": "Natal de novo"},
    ]
    res = source_messages(ROWS[:1], index_messages(chat))
    g = res["Natal"]
    assert g["matched"] == 1 and len(g["messages"]) == 1
    assert "06 12" not in g["messages"][0] and "adorei" in g["messages"][0]


def test_prompt_lists_allowed_names_apart_from_definitions():
    from ingestion.suggestions.subcategory import answer_schema

    p = build_prompt(
        "Salons & Beauty", [{"group": "X", "items": [], "messages": [], "context": ""}]
    )
    assert '["Cabelo", "Estética", "Tatuagem e Piercing"]' in p
    enum = answer_schema(KIND_SUBCATEGORIES[Kind.SALONS_AND_BEAUTY])["schema"][
        "properties"
    ]["r"]["items"]["properties"]["s"]["enum"]
    assert enum == ["Cabelo", "Estética", "Tatuagem e Piercing"]


def test_failed_batches_are_retried_once_in_smaller_batches():
    calls = []

    async def flaky(client, prompt, cfg, schema=None):
        calls.append(prompt)
        return None if len(calls) == 1 else {"r": [{"i": 0, "s": "Aéreo"}]}

    rows = [
        {
            "group": "Air France",
            "name": "Air France",
            "kind": "Transport",
            "items": [],
            "context": "ok",
            "date": "2025-01-01",
        }
    ]
    subs = asyncio.run(assign(build_group_records(rows, {}), flaky, None, None))
    assert subs == {"Air France": "Aéreo"} and len(calls) == 2
