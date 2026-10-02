"""Scope exclusions and Community Business qualification (#56).

Seams: the mentions builder with the extraction LLM mocked at the HTTP layer,
and the merge step (code-side exclusion list).
"""

import asyncio
import json
import os
from datetime import date

import httpx
import pandas as pd
import pytest

from habitantes.config import SuggestionsConfig
from habitantes.domain.suggestions import Kind
from ingestion.config import JevConfig, MentionExtractionConfig
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.mentions import read_mentions, run_mentions_builder
from ingestion.suggestions.merge import merge_variants
from ingestion.suggestions.suggestions import aggregate

os.environ.setdefault("OPENROUTER_API_KEY", "test")

EXCLUDED_TYPES = [
    "private_individual",
    "bank",
    "phone_operator",
    "app",
    "association",
    "public_service",
    "one_off_event",
]


def _csv(tmp_path):
    t = pd.Timestamp("2025-03-01 10:00:00")
    rows = [
        (t, "Ana", "Recomendo muito o Fulano, adorei", "statement"),
        (t + pd.Timedelta(minutes=1), "Bruno", "valeu", "statement"),
    ]
    p = tmp_path / "classified.csv"
    pd.DataFrame(rows, columns=["timestamp", "user", "message", "msg_type"]).to_csv(
        p, index=False
    )
    return p


def _mention(**over):
    base = {
        "name": "Padaria Brasil",
        "kind": "Markets & Groceries",
        "polarity": "positive",
        "items": [],
        "context": "Boa.",
        "date": "2025-03-01",
        "community_business": False,
        "business_identity": False,
        "entity_type": "business",
    }
    base.update(over)
    return base


def _extract(tmp_path, *mentions):
    sent = []

    def jev(request):
        return httpx.Response(200, json={"answers": {"has_suggestion": {"noul": 0.9}}})

    def llm(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"mentions": list(mentions)})}}
                ]
            },
        )

    async def go():
        jc = httpx.AsyncClient(transport=httpx.MockTransport(jev))
        lc = httpx.AsyncClient(transport=httpx.MockTransport(llm))
        try:
            return await run_mentions_builder(
                _csv(tmp_path),
                tmp_path,
                3,
                JevConfig(max_retries=1, retry_base_sleep_s=0),
                SuggestionsConfig(),
                MentionExtractionConfig(max_retries=1, retry_base_sleep_s=0),
                jev_client=jc,
                llm_client=lc,
            )
        finally:
            await jc.aclose()
            await lc.aclose()

    return read_mentions(asyncio.run(go())), sent


def test_real_business_is_kept(tmp_path):
    mentions, _ = _extract(tmp_path, _mention())
    assert [m.name for m in mentions] == ["Padaria Brasil"]
    assert mentions[0].community_business is False


@pytest.mark.parametrize("entity_type", EXCLUDED_TYPES)
def test_out_of_scope_entities_produce_no_mention(tmp_path, entity_type):
    mentions, _ = _extract(tmp_path, _mention(entity_type=entity_type))
    assert mentions == []


def test_exclusions_are_in_the_prompt_and_schema(tmp_path):
    _, sent = _extract(tmp_path, _mention())
    prompt = sent[0]["messages"][0]["content"]
    for word in ("bancos", "operadoras", "aplicativos", "associações", "evento"):
        assert word in prompt
    props = sent[0]["response_format"]["json_schema"]["schema"]["properties"]
    item = props["mentions"]["items"]["properties"]
    assert set(EXCLUDED_TYPES) <= set(item["entity_type"]["enum"])
    assert "business_identity" in item


def test_own_business_with_identity_is_a_community_business(tmp_path):
    mentions, _ = _extract(
        tmp_path, _mention(community_business=True, business_identity=True)
    )
    assert [m.community_business for m in mentions] == [True]


def test_own_business_without_identity_does_not_qualify(tmp_path):
    # name / personal number / member tag only: no Suggestion at all
    mentions, _ = _extract(
        tmp_path, _mention(community_business=True, business_identity=False)
    )
    assert mentions == []


def test_identity_flag_is_not_stored_and_no_contact_leaks(tmp_path):
    mentions, _ = _extract(
        tmp_path,
        _mention(
            community_business=True,
            business_identity=True,
            context="Instagram @loja_x, tel +33 6 12 34 56 78",
        ),
    )
    raw = mentions[0].model_dump_json()
    assert "business_identity" not in raw and "12 34 56" not in raw


def M(name, cb=False, kind=Kind.MARKETS_AND_GROCERIES):
    return Mention(
        name=name,
        kind=kind,
        polarity="positive",
        context="ok",
        date=date(2026, 1, 1),
        community_business=cb,
    )


@pytest.mark.parametrize(
    "name",
    [
        "BNP Paribas",
        "Crédit Agricole",
        "Société Générale",
        "Free Mobile",
        "SFR",
        "Bouygues Telecom",
        "WhatsApp",
        "Doctolib",
        "CAF",
        "CPAM",
        "Préfecture de l'Isère",
    ],
)
def test_merge_step_applies_the_exclusion_list(name):
    out = asyncio.run(merge_variants([M(name), M("Padaria Brasil")], None, None))
    assert [m.name for m in out] == ["Padaria Brasil"]


def test_advertiser_post_alone_is_not_offered_but_flag_flows():
    only_ad = aggregate([M("Casa", cb=True)])
    assert only_ad[0].counted == [] and only_ad[0].thumbs_up == 0
    both = aggregate([M("Casa", cb=True), M("Casa")])
    assert both[0].community_business is True and both[0].thumbs_up == 1
