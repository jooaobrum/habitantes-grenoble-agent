"""Compare business-level retrieval with batch-generated 'question -> recommendation' entries.

Approaches (all return N businesses per question; facts always come from our data):
  1 BIZ     business-level: expanded query + hybrid candidates (25 dense + 25 BM25) + LLM re-rank
  2 ENTRIES entries only: user question vs generated question+context, top entries' recommendations
  3 BIZ+Q   as 1, with each business's generated questions appended to its text (doc expansion)
  4 HYBRID  best-matching entry's recommendations first (if similar enough), filled from 3
Metrics: recall of the dataset's expected names, and an LLM judge (relevance, usefulness,
variety). Decide on `tune` (and the broad set); run `--split holdout` once for the winner.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from tests.eval.suggestions_index_experiment import (
    BM25,
    BROAD_QUESTIONS,
    EXPAND_PROMPT,
    JUDGE_PROMPT,
    N,
    PARSE_PROMPT,
    RERANK_VOTES_PROMPT,
    dense_text_v2,
    keyword_text,
    load_businesses,
    where,
)
from tests.eval.suggestions_kb_entries_experiment import render

BATCH = 55
GEN_PROMPT = """Você cria a base de conhecimento de recomendações de um assistente para brasileiros em Grenoble. Abaixo estão {n} negócios recomendados pela comunidade (tipo: {kind}). Analise TODOS juntos e crie entradas "pergunta -> recomendação".
Cada entrada:
- "question": pergunta natural que um recém-chegado faria no WhatsApp, em português; específica (cozinha, necessidade, produto, ocasião) ou ampla.
- "scope": "specific" ou "broad".
- "context": 1 a 2 frases resumindo o que a comunidade diz sobre essas opções; só fatos das fichas; sem inventar; sem citar mensagens nem pessoas.
- "ids": 2 a 6 ids (somente os ids abaixo) dos negócios que melhor respondem, do mais ao menos adequado; 1 id só se for único.
Regras: TODO negócio deve aparecer em ao menos uma entrada; não repita perguntas iguais ou quase iguais (se duas perguntas dariam as mesmas recomendações, una); entre {lo} e {hi} entradas; cubra pedidos específicos e amplos.
Responda em JSON: {{"entries":[{{"question":"...","scope":"specific","context":"...","ids":[0,1]}}]}}

Negócios (id | nome | tipo > subcategoria | descrição | itens | votos 👍/👎 | o que membros escreveram):
{lines}"""


async def build_entries(
    gs: List[Dict[str, Any]], d: Path, cl: Any, cfg: Any
) -> List[Dict[str, Any]]:
    """Entries for ALL businesses, in batches of <= BATCH sorted by Kind and subcategory (cached)."""
    from ingestion.suggestions.llm import chat_json

    cache = d / "quality_gate/kb_entries_full.jsonl"
    if cache.exists():
        return [json.loads(line) for line in open(cache)]
    ordered = sorted(gs, key=lambda g: (g["kind"], g["sub"] or ""))
    batches: List[List[Dict[str, Any]]] = []
    for kind in sorted({g["kind"] for g in ordered}):
        ks = [g for g in ordered if g["kind"] == kind]
        batches += [ks[i : i + BATCH] for i in range(0, len(ks), BATCH)]
    sem = asyncio.Semaphore(6)

    async def one(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        lines = "\n".join(
            f"{i} | {g['group']} | {where(g)} | {g['desc']} | {', '.join(x for x, _ in g['items'].most_common(4))} | {g['up']}/{g['down']} | "
            + " // ".join(m[:160] for m in g["msgs"][:2])
            for i, g in enumerate(batch)
        )
        n = len(batch)
        async with sem:
            res = await chat_json(
                cl,
                GEN_PROMPT.format(
                    n=n,
                    kind=batch[0]["kind"],
                    lo=max(6, n // 5),
                    hi=max(10, n // 2),
                    lines=lines,
                ),
                cfg,
            )
        out = []
        for e in (res or {}).get("entries", []):
            if isinstance(e.get("ids"), list) and e.get("question"):
                r = render(e, batch)
                if r["recommendations"]:
                    out.append({"kind": batch[0]["kind"], **r})
        return out

    entries = [
        e for part in await asyncio.gather(*[one(b) for b in batches]) for e in part
    ]
    cache.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
    return entries


async def main_async(split: str, broad: bool) -> None:  # pragma: no cover - network
    import httpx
    from dotenv import load_dotenv

    from habitantes.domain.suggestions import KIND_SUBCATEGORIES, Kind
    from habitantes.domain.tools._embedding import _embed_texts
    from ingestion.config import settings
    from ingestion.suggestions.llm import chat_json
    from tests.eval.suggestions_retrieval import (
        load_dataset,
        names_match,
        split_dataset,
    )

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    d = root / "artifacts/chat-19012021-02102026"
    gs = load_businesses(d)
    pos = {g["group"]: i for i, g in enumerate(gs)}
    cfg = settings.suggestion_llm.model_copy(
        update={"model": "google/gemini-2.5-flash"}
    )
    cl = httpx.AsyncClient(timeout=180)
    entries = await build_entries(gs, d, cl, cfg)
    qs = (
        [{"question": q, "expected": []} for q in BROAD_QUESTIONS]
        if broad
        else split_dataset(load_dataset(), split)
    )

    def norm(M: np.ndarray) -> np.ndarray:
        return M / np.linalg.norm(M, axis=1, keepdims=True)

    # entries -> businesses: coverage and per-business generated questions
    gen_q: Dict[str, List[str]] = collections.defaultdict(list)
    for e in entries:
        for r in e["recommendations"]:
            gen_q[r["name"]].append(e["question"])
    covered = sum(1 for g in gs if g["group"] in gen_q)
    print(
        f"entries {len(entries)} | businesses covered by >=1 entry {covered}/{len(gs)} ({covered / len(gs):.0%}) | avg recs/entry {sum(len(e['recommendations']) for e in entries) / len(entries):.1f}"
    )

    E_plain = norm(np.array(_embed_texts([dense_text_v2(g) for g in gs])))
    E_d2q = norm(
        np.array(
            _embed_texts(
                [
                    dense_text_v2(g)
                    + " Perguntas que responde: "
                    + " | ".join(gen_q.get(g["group"], [])[:4])
                    for g in gs
                ]
            )
        )
    )
    bm_plain = BM25([keyword_text(g) for g in gs])
    bm_d2q = BM25(
        [keyword_text(g) + " " + " ".join(gen_q.get(g["group"], [])[:4]) for g in gs]
    )
    E_ent = norm(
        np.array(_embed_texts([f"{e['question']} {e['context']}" for e in entries]))
    )
    sem = asyncio.Semaphore(8)

    async def llm(prompt: str) -> Dict[str, Any]:
        async with sem:
            return await chat_json(cl, prompt, cfg) or {}

    subs = "; ".join(
        f"{k.value}: {', '.join(v)}" for k, v in KIND_SUBCATEGORIES.items()
    )
    parsed = await asyncio.gather(
        *[
            llm(
                PARSE_PROMPT.format(
                    kinds=", ".join(k.value for k in Kind), subs=subs, q=q["question"]
                )
            )
            for q in qs
        ]
    )
    expanded = [
        str(r.get("query") or q["question"])
        for r, q in zip(
            await asyncio.gather(
                *[llm(EXPAND_PROMPT.format(q=q["question"])) for q in qs]
            ),
            qs,
        )
    ]
    Q1 = norm(np.array(_embed_texts([q["question"] for q in qs])))
    Q2 = norm(np.array(_embed_texts(expanded)))

    def biz_candidates(qi: int, E: np.ndarray, bm: BM25) -> List[int]:
        dense = np.argsort(-(E @ Q2[qi]))[:25].tolist()
        kw = np.argsort(
            -bm.scores(expanded[qi] + " " + " ".join(parsed[qi].get("terms") or []))
        )[:25].tolist()
        return list(dict.fromkeys(dense + kw))

    async def rerank(qi: int, cand: List[int]) -> List[int]:
        items = "\n".join(
            f"{i} | {gs[i]['group']} | {where(gs[i])} | {gs[i]['desc']} | {gs[i]['up']}/{gs[i]['down']}"
            for i in cand
        )
        r = await llm(
            RERANK_VOTES_PROMPT.format(q=qs[qi]["question"], items=items, n=N)
        )
        ids = [i for i in r.get("ids", []) if isinstance(i, int) and i in cand]
        return (list(dict.fromkeys(ids)) or cand)[:N]

    biz = await asyncio.gather(
        *[rerank(qi, biz_candidates(qi, E_plain, bm_plain)) for qi in range(len(qs))]
    )
    bizq = await asyncio.gather(
        *[rerank(qi, biz_candidates(qi, E_d2q, bm_d2q)) for qi in range(len(qs))]
    )
    sims = Q1 @ E_ent.T
    ent_only, hybrid, best_sim = [], [], []
    for qi in range(len(qs)):
        order = np.argsort(-sims[qi])
        best_sim.append(float(sims[qi][order[0]]))
        names: List[str] = []
        for oi in order[:3]:
            for r in entries[oi]["recommendations"]:
                if r["name"] not in names and r["name"] in pos:
                    names.append(r["name"])
        ent_only.append([pos[n] for n in names[:N]])
        first = (
            [
                pos[r["name"]]
                for r in entries[order[0]]["recommendations"]
                if r["name"] in pos
            ][:5]
            if sims[qi][order[0]] >= 0.55
            else []
        )
        hybrid.append(list(dict.fromkeys(first + bizq[qi]))[:N])
    approaches = {
        "1 BIZ (business-level, re-ranked)": biz,
        "2 ENTRIES only": ent_only,
        "3 BIZ + generated questions": bizq,
        "4 HYBRID (best entry first, then 3)": hybrid,
    }

    async def judge(qi: int, ids: List[int]) -> Dict[str, Any]:
        items = "\n".join(
            f"{j + 1}. {gs[i]['group']} | {where(gs[i])} | {gs[i]['desc']} | {gs[i]['up']}👍/{gs[i]['down']}👎"
            for j, i in enumerate(ids)
        )
        return (
            await llm(JUDGE_PROMPT.format(q=qs[qi]["question"], items=items))
            if ids
            else {}
        )

    judged = {
        a: await asyncio.gather(*[judge(qi, lst[qi]) for qi in range(len(qs))])
        for a, lst in approaches.items()
    }
    print(
        f"\n{split if not broad else 'broad'}: {len(qs)} questions | best-entry similarity median {float(np.median(best_sim)):.2f}"
    )
    print(f"{'approach':40s} recall@{N} hit | judge precision usefulness variety")
    for a, lst in approaches.items():
        tot = hit = anyhit = 0
        prec, use, var = [], [], []
        for qi, q in enumerate(qs):
            names = [{gs[i]["group"], *gs[i]["names"]} for i in lst[qi]]
            for e in q["expected"]:
                tot += 1
                hit += any(names_match(e, n) for ns in names for n in ns)
            anyhit += any(
                names_match(e, n) for e in q["expected"] for ns in names for n in ns
            )
            j = judged[a][qi]
            rel = j.get("relevant") or []
            if rel:
                prec.append(sum(bool(x) for x in rel) / len(rel))
            if isinstance(j.get("usefulness"), (int, float)):
                use.append(j["usefulness"])
            if isinstance(j.get("variety"), (int, float)):
                var.append(j["variety"])
        m = lambda x: sum(x) / len(x) if x else 0.0  # noqa: E731
        print(
            f"  {a:38s} {hit / max(tot, 1):.2f}  {anyhit / len(qs):.0%} |      {m(prec):.2f}      {m(use):.2f}      {m(var):.2f}"
        )
    out = d / f"quality_gate/compare_approaches_{'broad' if broad else split}.json"
    out.write_text(
        json.dumps(
            {
                "questions": [q["question"] for q in qs],
                "lists": {
                    a: [[gs[i]["group"] for i in lst] for lst in ls]
                    for a, ls in approaches.items()
                },
                "judged": judged,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    print("saved", out)


def main() -> None:  # pragma: no cover
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", choices=["tune", "holdout"], default="tune")
    p.add_argument("--broad", action="store_true")
    a = p.parse_args()
    asyncio.run(main_async(a.split, a.broad))


if __name__ == "__main__":
    main()
