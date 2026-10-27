"""Pseudo-labelled evaluation dataset: recommendation question -> expected Suggestions.

For a seeded sample of real Recommendation Requests in the chat, the reply window
that follows the request is run through the Mention extractor; the positive
Mentions become the *expected Suggestions* and an LLM rewrites the request into a
clean standalone question. Everything here is a pseudo-label: the maintainer
reviews it before it is trusted (see docs/SUGGESTIONS_EVAL.md).

Expected Suggestions are limited to what the group said in that Thread, so they
are a subset of what the full corpus would recommend.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import pandas as pd

from ingestion.preprocess.qa_pairs import detect_threads
from ingestion.suggestions.extract import Mention, scrub_phones
from ingestion.suggestions.windows import Window, is_request

Extractor = Callable[[Window], Awaitable[List[Mention]]]
Rewriter = Callable[[str, Window], Awaitable[Optional[str]]]
# (request, window, candidate names) -> names that directly answer the request,
# or None when the request is not asking for a business/place/product at all.
Judge = Callable[[str, Window, List[str]], Awaitable[Optional[List[str]]]]

MIN_LEN, MAX_LEN = 25, 250

REWRITE_PROMPT = """Reescreva o pedido de recomendação abaixo (de um grupo de WhatsApp \
de brasileiros em Grenoble) como UMA pergunta curta, clara e autônoma em português, \
como um novo membro a faria a um assistente. Remova nomes de pessoas, telefones e \
referências ao contexto ("alguém", "pessoal" pode ficar). Não cite nenhum nome de \
estabelecimento nem resposta. Responda em JSON: {{"question": "..."}}

Pedido: {request}"""


JUDGE_PROMPT = """Abaixo há um PEDIDO feito num grupo de WhatsApp e as mensagens que \
vieram depois (autores anonimizados). Responda em JSON:
{{"is_recommendation_request": true/false, "relevant": ["nome", ...]}}
- is_recommendation_request: o pedido quer indicação de um negócio, lugar, \
profissional ou produto específico? (dúvidas de procedimento, opiniões e \
curiosidades = false)
- relevant: quais dos NOMES CANDIDATOS foram de fato indicados como resposta a \
ESTE pedido (e não a outro assunto da conversa). Use exatamente os nomes dados.

PEDIDO: {request}

MENSAGENS:
{text}

NOMES CANDIDATOS: {names}"""


@dataclass(frozen=True)
class Candidate:
    thread_id: int
    request: str
    window: Window  # the request message and the replies that follow it


def find_candidates(df: pd.DataFrame, thread_gap_h: int, after: int) -> List[Candidate]:
    """Every request-with-question message, with the replies that follow it."""
    out: List[Candidate] = []
    for tid, thread_df in enumerate(detect_threads(df, thread_gap_h)):
        msgs = thread_df.to_dict(orient="records")
        for i, m in enumerate(msgs):
            text = str(m.get("message", "") or "")
            if "?" in text and MIN_LEN < len(text) < MAX_LEN and is_request(text):
                out.append(
                    Candidate(
                        tid,
                        re.sub(r"\s+", " ", text).strip(),
                        Window(tid, msgs[i : i + after + 1]),
                    )
                )
    return out


def expected_suggestions(mentions: List[Mention]) -> List[Dict[str, Any]]:
    """Positive Mentions collapsed to one entry per (name, Kind), best first."""
    acc: Dict[tuple, Dict[str, Any]] = {}
    for m in mentions:
        key = (re.sub(r"\W+", " ", m.name.lower()).strip(), m.kind.value)
        e = acc.setdefault(
            key,
            {
                "name": m.name,
                "kind": m.kind.value,
                "thumbs_up": 0,
                "thumbs_down": 0,
                "items": [],
                "community_business": False,
            },
        )
        e["thumbs_up" if m.polarity == "positive" else "thumbs_down"] += 1
        e["community_business"] |= m.community_business
        for it in m.items:
            if it not in e["items"]:
                e["items"].append(it)
    kept = [e for e in acc.values() if e["thumbs_up"] > e["thumbs_down"]]
    return sorted(kept, key=lambda e: (-e["thumbs_up"], e["name"].lower()))


async def build_case(
    cand: Candidate,
    extract: Extractor,
    rewrite: Rewriter,
    judge: Optional[Judge] = None,
) -> Optional[Dict[str, Any]]:
    """One dataset case, or None when the replies hold no positive Suggestion."""
    mentions = await extract(cand.window)
    expected = expected_suggestions(mentions)
    if not expected:
        return None
    if judge is not None:
        relevant = await judge(cand.request, cand.window, [e["name"] for e in expected])
        if not relevant:  # not a recommendation request, or nothing answers it
            return None
        wanted = {re.sub(r"\W+", " ", n.lower()).strip() for n in relevant}
        expected = [
            e
            for e in expected
            if re.sub(r"\W+", " ", e["name"].lower()).strip() in wanted
        ]
        if not expected:
            return None
    question = await rewrite(cand.request, cand.window)
    if not question:
        return None
    kind = Counter(e["kind"] for e in expected).most_common(1)[0][0]
    return {
        "thread_id": cand.thread_id,
        "question": question.strip(),
        "original_request": scrub_phones(cand.request),
        "kind": kind,
        "expected_suggestions": expected,
        "status": "pseudo",  # becomes "reviewed" once the maintainer checks it
    }


async def build_dataset(
    candidates: List[Candidate],
    extract: Extractor,
    rewrite: Rewriter,
    n_requests: int,
    seed: int = 42,
    concurrency: int = 8,
    judge: Optional[Judge] = None,
) -> List[Dict[str, Any]]:
    """Cases for a seeded sample of `n_requests` candidates (fewer if none qualify)."""
    sample = random.Random(seed).sample(candidates, min(n_requests, len(candidates)))
    sem = asyncio.Semaphore(concurrency)

    async def one(c: Candidate) -> Optional[Dict[str, Any]]:
        async with sem:
            return await build_case(c, extract, rewrite, judge)

    cases = [c for c in await asyncio.gather(*[one(c) for c in sample]) if c]
    cases.sort(key=lambda c: c["thread_id"])
    for i, c in enumerate(cases, 1):
        c["id"] = f"rec-pseudo-{i:03d}"
    return cases


def make_real_rewriter() -> Rewriter:  # pragma: no cover - needs network
    import httpx

    from ingestion.config import settings
    from ingestion.suggestions.llm import chat_json

    client = httpx.AsyncClient()

    async def run(request: str, _window: Window) -> Optional[str]:
        data = await chat_json(
            client,
            REWRITE_PROMPT.format(request=scrub_phones(request)),
            settings.suggestion_llm,
        )
        q = (data or {}).get("question")
        return q if isinstance(q, str) and q.strip() else None

    return run


def make_real_judge(model: Optional[str] = None) -> Judge:  # pragma: no cover
    import httpx

    from ingestion.config import settings
    from ingestion.suggestions.extract import pseudonymise
    from ingestion.suggestions.llm import chat_json

    client = httpx.AsyncClient()

    async def run(
        request: str, window: Window, names: List[str]
    ) -> Optional[List[str]]:
        text, _ = pseudonymise(window)
        data = await chat_json(
            client,
            JUDGE_PROMPT.format(
                request=scrub_phones(request),
                text=text,
                names=json.dumps(names, ensure_ascii=False),
            ),
            settings.suggestion_llm.model_copy(update={"model": model})
            if model
            else settings.suggestion_llm,
        )
        if not data or not data.get("is_recommendation_request"):
            return None
        rel = data.get("relevant")
        return [n for n in rel if isinstance(n, str)] if isinstance(rel, list) else None

    return run


def main() -> None:  # pragma: no cover - CLI glue
    from ingestion.config import settings
    from ingestion.suggestions.labelling import load_classified
    from ingestion.suggestions.measure import make_real_extractor

    root = Path(__file__).parents[2]
    default_csv = (
        root
        / settings.artifacts_dir
        / Path(settings.input_file).stem
        / "classified.csv"
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=default_csv)
    p.add_argument("--output", type=Path, default=None, help="pseudo_dataset.jsonl")
    p.add_argument("--n", type=int, default=150, help="requests to sample")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--after", type=int, default=settings.suggestions.window_after_request
    )
    p.add_argument("--judge-model", default=None, help="stronger model for the judge")
    args = p.parse_args()

    cands = find_candidates(
        load_classified(args.input), settings.qa.thread_gap_h, args.after
    )
    cases = asyncio.run(
        build_dataset(
            cands,
            make_real_extractor(),
            make_real_rewriter(),
            args.n,
            args.seed,
            judge=make_real_judge(args.judge_model),
        )
    )
    out = args.output or args.input.parent / "pseudo_dataset.jsonl"
    out.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8",
    )
    print(f"{len(cands)} requests found; {len(cases)} cases kept -> {out}")


if __name__ == "__main__":
    main()
