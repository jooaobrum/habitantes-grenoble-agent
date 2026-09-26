"""Jev as the ingestion gate: qa_pairs wiring, synthesis filter, loader filter.

Jev's HTTP layer is mocked with httpx.MockTransport: no network.
"""

import asyncio

import httpx
import pandas as pd

from ingestion.config import JevConfig
from ingestion.load.qdrant import should_drop
from ingestion.pipeline import select_for_synthesis
from ingestion.preprocess.qa_pairs import extract_qa_pairs


def _csv(tmp_path):
    rows = [
        (
            "2025-03-01 10:00:00",
            "ana",
            "Como renovar o titre de séjour na préfecture?",
            "question",
        ),
        (
            "2025-03-01 10:05:00",
            "bob",
            "Você precisa entrar no site da ANEF e preencher o formulário. https://www.service-public.fr",
            "answer",
        ),
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "user", "message", "msg_type"])
    p = tmp_path / "classified.csv"
    df.to_csv(p, index=False)
    return p


def _jev_response(value="HIGH", confidence=0.9, topic="Housing & CAF", review=0.1):
    return {
        "answers": {
            "value": {"choice": value, "confidence": confidence, "probabilities": {}},
            "topic": {"choice": topic},
            "outdated": {"noul": 0.0},
            "needs_review": {"noul": review},
        }
    }


def _run(tmp_path, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = JevConfig(max_retries=1, retry_base_sleep_s=0)

    async def go():
        try:
            return await extract_qa_pairs(
                _csv(tmp_path),
                3,
                2,
                5,
                50,
                20,
                jev=cfg,
                jev_client=client,
            )
        finally:
            await client.aclose()

    import os

    os.environ.setdefault("OPENROUTER_API_KEY", "test")
    return asyncio.run(go())


def test_extract_uses_jev_value_and_keeps_heuristics(tmp_path):
    pairs = _run(tmp_path, lambda r: httpx.Response(200, json=_jev_response()))
    assert len(pairs) == 1
    p = pairs[0]
    assert p["value"] == "HIGH"
    assert p["value_source"] == "jev"
    assert p["topic"] == "Housing & CAF"
    assert p["heuristic_topic"] == "Visa & Residency"
    assert p["heuristic_tier"] in ("high", "medium", "low")
    assert isinstance(p["heuristic_score"], int)


def test_extract_falls_back_to_heuristic_when_low_confidence(tmp_path):
    pairs = _run(
        tmp_path, lambda r: httpx.Response(200, json=_jev_response("LOW", 0.2))
    )
    p = pairs[0]
    assert p["value_source"] == "heuristic_fallback"
    assert p["value"] == p["heuristic_tier"].upper()


def test_extract_falls_back_when_call_fails(tmp_path):
    pairs = _run(tmp_path, lambda r: httpx.Response(500))
    assert pairs[0]["value_source"] == "heuristic_fallback"
    assert pairs[0]["topic"] == "Visa & Residency"


def test_synthesis_filter_uses_value():
    qa = [
        {"value": "HIGH", "tier": "low"},
        {"value": "MEDIUM", "tier": "low"},
        {"value": "LOW", "tier": "high"},
        {"value": "UNKNOWN", "tier": "high"},
        {"tier": "high"},
    ]
    assert select_for_synthesis(qa) == qa[:2]


def _rec(**over):
    rec = {
        "category": "Visa & Residency",
        "key_terms": ["visto"],
        "answer": "Ok",
        "confidence": 0.9,
        "question": "Como renovar?",
        "value": "HIGH",
    }
    rec.update(over)
    return rec


def test_loader_keeps_good_record():
    assert should_drop(_rec()) == (False, [])


def test_loader_drops_low_and_unknown_value():
    assert should_drop(_rec(value="LOW"))[0] is True
    assert should_drop(_rec(value="UNKNOWN"))[0] is True
    # heuristic tier no longer gates
    assert should_drop(_rec(tier="low"))[0] is False


def test_loader_jev_needs_review_is_primary():
    assert should_drop(_rec(jev_needs_review=True))[0] is True
    # Jev says fine -> synthesis LLM flag ignored
    assert (
        should_drop(_rec(jev_needs_review=False, needs_human_review=True))[0] is False
    )
    # no Jev verdict -> fall back to synthesis flag
    assert should_drop(_rec(jev_needs_review=None, needs_human_review=True))[0] is True


def test_loader_synthesis_confidence_check_untouched():
    drop, reasons = should_drop(_rec(confidence=0.5, jev_needs_review=False))
    assert drop and "confidence<0.65" in reasons


def test_synthesis_keeps_jev_topic_and_outdated():
    import asyncio
    from types import SimpleNamespace
    from ingestion.preprocess.synthesis import SynthesisResult, synthesize_qa

    parsed = SynthesisResult(
        subcategory="Other",
        question="q",
        answer="a",
        answer_confirmed=False,
        info_might_be_outdated=False,
        tags=["x"],
        key_terms=["y"],
        confidence=0.9,
        needs_human_review=False,
    )
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
    )

    class C:
        class beta:
            class chat:
                class completions:
                    @staticmethod
                    async def parse(**kw):
                        return resp

    row = {
        "topic": "Visa & Residency",
        "jev_outdated": True,
        "question": "q",
        "answer": "a",
    }
    out = asyncio.run(synthesize_qa(C(), "{qa_record_json}", row))
    assert out["category"] == "Visa & Residency"
    assert out["info_might_be_outdated"] is True
