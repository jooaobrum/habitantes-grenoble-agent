"""Unit tests for the Jev classifier (ingestion/preprocess/jev.py).

The HTTP layer is mocked with httpx.MockTransport: no network, no spend.
"""

import json

import httpx

from ingestion.preprocess.jev import classify_qa

CONTEXT = [
    {"user": "Bruna Moya", "message": "E quanto tempo demorou?"},
    {"user": "João Victor", "message": "Uns dois meses"},
]


def _row(**over):
    row = {
        "thread_id": "t1",
        "question": "Quanto tempo leva o visto?",
        "answer": "Uns dois meses.",
        "context": CONTEXT,
        "tier": "medium",
        "topic": "Visa & Residency",
    }
    row.update(over)
    return row


def _jev_payload(value="HIGH", confidence=0.9, topic="Housing & CAF"):
    return {
        "model": "typesafe/jev-1.13",
        "answers": {
            "value": {
                "type": "choice",
                "choice": value,
                "probabilities": {
                    "UNKNOWN": 0,
                    "LOW": 0.05,
                    "MEDIUM": 0.05,
                    "HIGH": 0.9,
                },
                "confidence": confidence,
            },
            "topic": {
                "type": "choice",
                "choice": topic,
                "probabilities": {topic: 0.98},
                "confidence": 0.98,
            },
            "outdated": {"type": "noul", "noul": 0.7},
            "needs_review": {"type": "noul", "noul": 0.2},
        },
        "usage": {"cost": 0.00003},
    }


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _run(handler, row=None, **kw):
    async with _client(handler) as client:
        return await classify_qa(
            client,
            row or _row(),
            api_key="k",
            retry_base_sleep_s=0,
            **kw,
        )


async def test_successful_call():
    seen = {}

    def handler(request: httpx.Request):
        seen["req"] = request
        return httpx.Response(200, json=_jev_payload())

    out = await _run(handler)

    assert out["value"] == "HIGH"
    assert out["value_confidence"] == 0.9
    assert out["value_probabilities"]["HIGH"] == 0.9
    assert out["topic"] == "Housing & CAF"
    assert out["jev_outdated"] is True
    assert out["jev_needs_review"] is False
    assert out["value_source"] == "jev"
    assert out["thread_id"] == "t1"  # original fields preserved

    req = seen["req"]
    assert str(req.url) == "https://openrouter.ai/api/alpha/decisions"
    assert req.headers["authorization"] == "Bearer k"
    body = json.loads(req.content)
    assert body["model"] == "~typesafe/jev-latest"
    assert set(body["questions"]) >= {"value", "topic", "outdated", "needs_review"}


async def test_context_never_includes_user():
    seen = {}

    def handler(request: httpx.Request):
        seen["raw"] = request.content.decode()
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_jev_payload())

    await _run(handler)

    assert "Bruna Moya" not in seen["raw"]
    assert "João Victor" not in seen["raw"]
    assert '"user"' not in seen["raw"]
    assert "E quanto tempo demorou?" in seen["raw"]
    assert "Uns dois meses" in seen["raw"]


async def test_low_confidence_is_unknown():
    def handler(request):
        return httpx.Response(200, json=_jev_payload(value="HIGH", confidence=0.4))

    out = await _run(handler, row=_row(tier="low", topic="Visa & Residency"))

    assert out["value_source"] == "low_confidence"
    assert out["value"] == "UNKNOWN"
    assert out["value_confidence"] == 0.4
    assert out["topic"] == "Visa & Residency"


async def test_confidence_threshold_is_configurable():
    def handler(request):
        return httpx.Response(200, json=_jev_payload(confidence=0.7))

    out = await _run(handler, confidence_threshold=0.8)
    assert out["value_source"] == "low_confidence"
    assert out["value"] == "UNKNOWN"


async def test_retry_exhausted_is_unknown():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(500, json={"error": "boom"})

    out = await _run(handler, row=_row(tier="high"), max_retries=3)

    assert calls["n"] == 3
    assert out["value_source"] == "jev_unavailable"
    assert out["value"] == "UNKNOWN"
    assert out["value_confidence"] is None
    assert out["jev_outdated"] is None
    assert out["jev_needs_review"] is None


async def test_retry_then_success():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=_jev_payload())

    out = await _run(handler, max_retries=3)
    assert calls["n"] == 2
    assert out["value_source"] == "jev"
