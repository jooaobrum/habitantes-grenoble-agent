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
        return httpx.Response(200, json={"answers": {"has_suggestion": {"noul": 0.99}}})

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


def test_recommendation_notice_added_when_missing():
    from habitantes.domain.agent import _ensure_recommendation_notice

    out = _ensure_recommendation_notice(
        "- **A** — 3👍/0👎 · última menção 01/01/2025 — x"
    )
    assert "não uma lista exaustiva" in out and "Confirme a disponibilidade" in out


def test_recommendation_notice_not_duplicated_and_sources_block_removed():
    from habitantes.domain.agent import _ensure_recommendation_notice

    ans = (
        "Resumo das principais indicações:\n- **A** — 3👍/0👎\n"
        "Confirme a disponibilidade e os horários.\n\n"
        "Fontes mencionadas no contexto:\n- A"
    )
    out = _ensure_recommendation_notice(ans)
    assert out.count("Confirme") == 1 and "Fontes mencionadas" not in out
    assert "exaustiva" not in out  # "Resumo" already present: no second notice


def _cl(*members):
    return {"members": list(members)}


def _mem(name, up, down=0, **kw):
    return {
        "name": name,
        "thumbs_up": up,
        "thumbs_down": down,
        "last_date": "2025-03-12",
        "items": ["clareamento"],
        **kw,
    }


def test_render_uses_tool_counts_and_drops_invented_names():
    from habitantes.domain.agent import _render_recommendation

    clusters = [
        _cl(_mem("Dr Martin", 5), _mem("Clinique Alpes", 3, community_business=True))
    ]
    out = _render_recommendation(
        "Indico o Dr Martin e a Boulanger, e também a Clinique Alpes.", clusters
    )
    assert "- **Dr Martin** — 5👍/0👎 · última menção 12/03/2025" in out
    assert "[negócio de membro do grupo — divulgação própria]" in out
    assert "Boulanger" not in out
    assert "Confirme a disponibilidade" in out and "resumo" in out


def test_render_keeps_answer_when_no_returned_name_is_mentioned():
    from habitantes.domain.agent import _render_recommendation

    assert (
        _render_recommendation(
            "A comunidade não indicou nada.", [_cl(_mem("Dr Martin", 5))]
        )
        is None
    )


def test_render_caps_picks_and_skips_net_negative():
    from habitantes.domain.agent import _render_recommendation

    members = [_mem(f"Lugar{c}", 3) for c in "ABCDEFG"] + [_mem("Ruim", 1, 4)]
    text = " ".join(m["name"] for m in members)
    out = _render_recommendation(text, [_cl(*members)])
    assert out.count("- **") == 7 and "Ruim" not in out


def test_no_picks_web_nudge_restates_question():
    from habitantes.domain.agent import _NO_PICKS_WEB_NUDGE

    assert "web_search_grenoble" in _NO_PICKS_WEB_NUDGE
    assert "pedido original" in _NO_PICKS_WEB_NUDGE
    assert "oficina" in _NO_PICKS_WEB_NUDGE.format(question="onde acho oficina?")
