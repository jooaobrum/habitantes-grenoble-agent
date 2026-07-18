"""Unit tests for the Tavily web_search tool.

httpx and settings are mocked so no real Tavily service or config is needed.
Exercises: Grenoble scope enforcement, the {"results"}/{"error"} contract,
missing-key disabling, and timeout classification.
"""

from types import SimpleNamespace

import httpx
import pytest

import habitantes.domain.tools.web_search as ws
from habitantes import config as config_module
from habitantes.config import WebSearchConfig


def _fake_settings(api_key: str = "test-key"):
    """A stand-in Settings object exposing only .web_search."""
    return SimpleNamespace(web_search=WebSearchConfig(tavily_api_key=api_key))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# ── _scope_query ──────────────────────────────────────────────────────────────


def test_scope_query_appends_when_grenoble_absent():
    assert ws._scope_query("melhores restaurantes", "Grenoble France") == (
        "melhores restaurantes Grenoble France"
    )


def test_scope_query_leaves_query_when_grenoble_present():
    q = "quantos habitantes tem Grenoble"
    assert ws._scope_query(q, "Grenoble France") == q


def test_scope_query_is_accent_and_case_insensitive():
    # "Grénoble"/"GRENOBLE" already reference the city → no suffix added.
    assert (
        ws._scope_query("clima em GRÉNOBLE", "Grenoble France") == "clima em GRÉNOBLE"
    )


# ── web_search() contract ─────────────────────────────────────────────────────


def test_web_search_success_returns_results_contract(monkeypatch):
    monkeypatch.setattr(config_module, "load_settings", lambda: _fake_settings())

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse(
            {
                "results": [
                    {
                        "title": "Grenoble - Wikipédia",
                        "url": "https://fr.wikipedia.org/wiki/Grenoble",
                        "content": "Grenoble tem cerca de 158 mil habitantes.",
                        "score": 0.91,
                        "published_date": "2025-01-01",
                    }
                ]
            }
        )

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.web_search("quantos habitantes")

    assert "results" in result
    assert len(result["results"]) == 1
    r = result["results"][0]
    assert set(r.keys()) == {"title", "url", "content", "score", "published_date"}
    # Grenoble scope enforced on the outgoing query.
    assert "Grenoble" in captured["json"]["query"]
    # API key passed as a Bearer token.
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_web_search_disabled_when_no_key(monkeypatch):
    monkeypatch.setattr(config_module, "load_settings", lambda: _fake_settings(""))
    # httpx.post must never be reached.
    monkeypatch.setattr(
        ws.httpx,
        "post",
        lambda *a, **k: pytest.fail("httpx.post should not be called without a key"),
    )

    result = ws.web_search("qualquer coisa")

    assert result["error"]["error_code"] == "WEB_SEARCH_DISABLED"
    assert result["error"]["retryable"] is False


def test_web_search_timeout_is_classified(monkeypatch):
    monkeypatch.setattr(config_module, "load_settings", lambda: _fake_settings())

    def fake_post(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.web_search("evento em Grenoble")

    assert result["error"]["error_code"] == "WEB_SEARCH_TIMEOUT"
    assert result["error"]["retryable"] is True


def test_web_search_unreachable_on_other_error(monkeypatch):
    monkeypatch.setattr(config_module, "load_settings", lambda: _fake_settings())

    def fake_post(*a, **k):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(ws.httpx, "post", fake_post)

    result = ws.web_search("evento em Grenoble")

    assert result["error"]["error_code"] == "WEB_SEARCH_UNREACHABLE"


# ── @tool wrapper: failures stay soft (never an {"error"} dict) ───────────────


def test_tool_wrapper_returns_soft_string_on_error(monkeypatch):
    monkeypatch.setattr(config_module, "load_settings", lambda: _fake_settings())
    monkeypatch.setattr(
        ws, "web_search", lambda query: {"error": {"error_code": "X", "message": "y"}}
    )

    tool = ws.get_web_search_tool()
    out = tool.invoke({"query": "algo"})

    assert isinstance(out, str)
    assert "indisponível" in out


def test_tool_wrapper_formats_results(monkeypatch):
    monkeypatch.setattr(config_module, "load_settings", lambda: _fake_settings())
    monkeypatch.setattr(
        ws,
        "web_search",
        lambda query: {
            "results": [
                {
                    "title": "T",
                    "url": "https://example.org/x",
                    "content": "corpo",
                    "score": 0.5,
                    "published_date": "2025-06-01",
                }
            ]
        },
    )

    tool = ws.get_web_search_tool()
    out = tool.invoke({"query": "algo"})

    assert isinstance(out, dict)
    assert "https://example.org/x" in out["formatted"]
    assert out["results"][0]["title"] == "T"
