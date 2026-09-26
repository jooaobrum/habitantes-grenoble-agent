"""Tavily web search — a lower-priority, Grenoble-scoped secondary source.

Mirrors the tool pattern in `search.py`: a plain `web_search()` function returning
the `{"results": [...]}` / `{"error": {...}}` dict contract, plus a LangChain
`@tool` wrapper (`web_search_grenoble`) and a lazy `get_web_search_tool()`
singleton for the ReAct agent.

The KB (Qdrant) is always the preferred source. Web is used for factual/current/
generalist Grenoble info or to confirm possibly-outdated facts. Every query is
forced to Grenoble scope via `_scope_query`.
"""

import logging
from typing import Any

import httpx

from ._ranking import strip_accents

logger = logging.getLogger(__name__)


def _scope_query(query: str, suffix: str) -> str:
    """Force Grenoble scope: append `suffix` unless the query already mentions it.

    Matching is accent-insensitive and lowercased so "Grénoble"/"GRENOBLE" count.
    """
    normalized = strip_accents(query).lower()
    if "grenoble" in normalized:
        return query
    return f"{query} {suffix}".strip()


def _classify_web_error(exc: Exception) -> str:
    """Map a raised httpx exception to WEB_SEARCH_TIMEOUT or WEB_SEARCH_UNREACHABLE."""
    if isinstance(exc, httpx.TimeoutException):
        return "WEB_SEARCH_TIMEOUT"
    return "WEB_SEARCH_UNREACHABLE"


# ── Public tool function ──────────────────────────────────────────────────────


def web_search(
    query: str, scope_to_grenoble: bool = True, news: bool = False
) -> dict[str, Any]:
    """Grenoble-scoped Tavily web search.

    Args:
        query: Natural-language query (Portuguese/French mixed). Grenoble scope is
               added by default.
        scope_to_grenoble: Append the Grenoble location suffix (default). Set False
               for generic, non-local queries (national rules, astronomy, vocabulary).
        news: Use Tavily's "news" topic (weather, events, current affairs).

    Returns:
        {"results": [{"title", "url", "content", "score", "published_date"}, ...]}
        or
        {"error": {"error_code", "message", "retryable"}}
    """
    from habitantes.config import load_settings

    cfg = load_settings().web_search

    if not cfg.tavily_api_key:
        return {
            "error": {
                "error_code": "WEB_SEARCH_DISABLED",
                "message": "Tavily API key not configured.",
                "retryable": False,
            }
        }

    scoped = _scope_query(query, cfg.location_suffix) if scope_to_grenoble else query

    try:
        response = httpx.post(
            cfg.api_url,
            headers={"Authorization": f"Bearer {cfg.tavily_api_key}"},
            json={
                "query": scoped,
                "max_results": cfg.max_results,
                "search_depth": cfg.search_depth,
                "topic": "news" if news else cfg.topic,
            },
            timeout=cfg.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        error_code = _classify_web_error(exc)
        logger.error("Tavily %s: %s", error_code, exc)
        return {
            "error": {
                "error_code": error_code,
                "message": str(exc),
                "retryable": True,
            }
        }

    results = []
    for r in data.get("results", []):
        results.append(
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": float(r.get("score", 0.0) or 0.0),
                "published_date": r.get("published_date", ""),
            }
        )

    return {"results": results}


# ── LangChain tool wrapper (for ReAct agent) ─────────────────────────────────


def _format_web_results(results: list[dict]) -> str:
    """Format web results into a numbered context block with URLs for citation."""
    parts = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        date = r.get("published_date", "")
        header = f"[{i}] {title}".rstrip()
        if date:
            header += f" | Data: {date}"
        parts.append(f"{header}\nURL: {url}\n{content}")
    return "\n\n".join(parts)


def _make_web_search_tool():
    """Create a LangChain tool wrapping web_search for use with bind_tools."""
    from langchain_core.tools import tool

    @tool
    def web_search_grenoble(
        query: str, scope_to_grenoble: bool = True, news: bool = False
    ) -> Any:
        """Search the web for information about Grenoble, France (lower priority).

        This is a SECONDARY source — always prefer search_knowledge_base first.
        Use this tool when the knowledge base is insufficient, or when the question
        needs factual/current/generalist information about Grenoble (e.g. number of
        inhabitants, current events, current official procedures).

        ALSO use it to double-check a knowledge-base result that LOOKS complete but
        falls into a perishable-data category, because these change over time and a
        community thread may simply be out of date or wrong:
          - money amounts: prices, fees, bonuses, promo codes, fines, salaries
          - transport schedules, routes, or frequency (trains, buses, flights, trams)
          - required documents or official procedure rules (visas, residency permits,
            CAF, taxes) — checklists like this change, and community answers about
            them can be incomplete or simply incorrect.
        Do not skip the check just because the knowledge-base chunk already contains a
        specific number or a confident-sounding claim in one of these categories.

        The users are Brazilians living in Grenoble: when they ask about a document
        (passport, CNH, RG, certificates) without naming a country, query the
        BRAZILIAN document (e.g. "passeport brésilien consulat Marseille"), not the
        French one.

        Grenoble scope is added to the query by default. You may call this tool up to
        3 times per question to refine a search that did not answer the question.

        Args:
            query: The search query, PHRASED IN FRENCH regardless of the
                   conversation's language (Portuguese, English, etc.). Official
                   and local sources for Grenoble (service-public.fr, préfecture,
                   Météo France, local news) are in French, so a French query
                   returns far better results than a translated one. Grenoble
                   scope is added automatically — no need to add it yourself.
            scope_to_grenoble: True (default) appends "Grenoble France" to the
                   query. Pass False for generic, non-local questions (national
                   rules, astronomy, product vocabulary in French).
            news: True to search recent news/current events (weather, events,
                   current office-holders). Default False.
        """
        result = web_search(query, scope_to_grenoble, news)

        # Keep failures soft: never surface an {"error"} dict to the loop — a web
        # outage must not hard-fail a turn. Return a friendly PT string instead.
        if "error" in result:
            return "Busca web indisponível no momento."

        results = result.get("results", [])
        if not results:
            return "Nenhum resultado encontrado na web para esta busca."

        return {
            "formatted": _format_web_results(results),
            "results": results,
        }

    return web_search_grenoble


# Lazy singleton
_web_search_tool = None


def get_web_search_tool():
    """Return the LangChain tool for web_search_grenoble (singleton)."""
    global _web_search_tool
    if _web_search_tool is None:
        _web_search_tool = _make_web_search_tool()
    return _web_search_tool
