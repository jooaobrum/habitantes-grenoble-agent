"""Compare retrieval strategies for business-level Suggestions, with metrics AND an LLM judge.

Strategies A..H vary the indexed text (raw vs rewritten description), dense vs hybrid
(dense + BM25), a Kind / subcategory filter parsed from the question, a quality blend,
and a mix across subcategories for broad requests. Each returns N businesses per
question. Metrics: recall of the dataset's expected names, and an LLM judge's per-item
relevance, list usefulness and (for broad requests) variety.

Decisions are made on the `tune` split only; run `--split holdout` once for the winner.
Needs artifacts from the pipeline (grouped_mentions_filtered_subcategory.jsonl,
quality_gate/source_messages.jsonl, quality_gate/index_descriptions.json) and API keys.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from habitantes.domain.suggestions import (
    KIND_KEYWORDS_PT,
    KIND_SUBCATEGORIES,
    Kind,
)

N = 8
BROAD_QUESTIONS = [
    "Alguém recomenda restaurantes em Grenoble?",
    "Indicação de dentista em Grenoble?",
    "Quais médicos vocês recomendam em Grenoble?",
    "Onde posso ir para tomar uma cerveja ou beber em Grenoble?",
    "Quais supermercados vocês recomendam em Grenoble?",
    "Indicação de cabeleireiro ou salão em Grenoble?",
    "Alguém indica academia ou lugar para fazer esporte?",
    "Vocês recomendam algum lugar para fazer compras em Grenoble?",
    "Quais empresas ou serviços de transporte vocês recomendam para viajar?",
    "Alguém indica aulas ou cursos em Grenoble?",
    "Tem algum veterinário ou serviço para pets que vocês recomendam?",
    "Quais lugares vocês recomendam para passear perto de Grenoble?",
]
TODAY = date(2026, 10, 2)


def strip(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def wilson(up: int, down: int, z: float = 1.0) -> float:
    n = up + down
    if n == 0:
        return 0.0
    p = up / n
    return (
        p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    ) / (1 + z * z / n)


def quality(g: Dict[str, Any]) -> float:
    """Lower-confidence 👍 share x recency (2-year half-life) x mild boost per Mention."""
    age = (TODAY - date.fromisoformat(g["last"])).days / 365
    return (
        wilson(g["up"], g["down"])
        * (0.5 + 0.5 * 0.5 ** (age / 2))
        * math.log2(2 + g["up"] + g["down"])
    )


class BM25:
    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.toks = [strip(d).split() for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.toks)) / len(self.toks)
        df = collections.Counter(t for d in self.toks for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [collections.Counter(d) for d in self.toks]

    def scores(self, query: str) -> np.ndarray:
        q = [t for t in strip(query).split() if t in self.idf]
        out = np.zeros(len(self.toks))
        for i, tf in enumerate(self.tf):
            ln = len(self.toks[i])
            for t in q:
                f = tf.get(t, 0)
                if f:
                    out[i] += (
                        self.idf[t]
                        * f
                        * (self.k1 + 1)
                        / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
                    )
        return out


def load_businesses(d: Path) -> List[Dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in open(d / "grouped_mentions_filtered_subcategory.jsonl")
    ]
    src = {
        json.loads(line)["group"]: json.loads(line)["messages"]
        for line in open(d / "quality_gate/source_messages.jsonl")
    }
    desc = json.load(open(d / "quality_gate/index_descriptions.json"))
    G: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        g = G.setdefault(
            r["group"],
            {
                "group": r["group"],
                "kind": r["kind"],
                "sub": r["subcategory"],
                "up": 0,
                "down": 0,
                "last": "0",
                "items": collections.Counter(),
                "ctx": [],
                "names": set(),
            },
        )
        g["up"] += r["polarity"] == "positive"
        g["down"] += r["polarity"] != "positive"
        g["last"] = max(g["last"], r["date"])
        g["names"].add(r["name"])
        for i in r["items"]:
            g["items"][i] += 1
        if r["polarity"] == "positive" and len(g["ctx"]) < 2:
            g["ctx"].append(r["context"])
    out = []
    for g in G.values():
        if g["up"] > g["down"] and g["group"] in desc:
            g["desc"] = desc[g["group"]]["descricao"]
            g["terms"] = desc[g["group"]]["termos"]
            g["msgs"] = src.get(g["group"], [])
            g["q"] = quality(g)
            out.append(g)
    return out


def items_of(g: Dict[str, Any]) -> str:
    return ", ".join(i for i, _ in g["items"].most_common(5))


def where(g: Dict[str, Any]) -> str:
    return g["kind"] + (" > " + g["sub"] if g["sub"] else "")


def dense_text_raw(g: Dict[str, Any]) -> str:
    return f"{g['group']}. {items_of(g)}. {' '.join(g['ctx'])[:200]}"


def dense_text_v2(g: Dict[str, Any]) -> str:
    return f"{g['group']} ({where(g)}). {g['desc']} Termos: {', '.join(g['terms'])}."


def keyword_text(g: Dict[str, Any]) -> str:
    kw = " ".join(KIND_KEYWORDS_PT.get(Kind(g["kind"]), ()))
    return f"{g['group']} {' '.join(g['names'])} {' '.join(g['terms'])} {items_of(g)} {g['sub'] or ''} {kw}"


PARSE_PROMPT = """Entenda o pedido de um usuário que procura indicações em Grenoble.
Tipos (kind) possíveis: {kinds}.
Subcategorias por tipo: {subs}
Responda em JSON: {{"kind": "<tipo ou vazio>", "subcategory": "<subcategoria do tipo ou vazio>", "terms": ["palavras que estreitam o pedido, ex.: japonês, pediatra"], "broad": true/false}}
- kind: só se o pedido deixa claro; senão vazio. subcategory: só se o pedido implica claramente UMA subcategoria; senão vazio.
- broad = true quando o pedido é só o tipo ("restaurantes", "dentista") sem nada que estreite; false quando há um termo que estreita (cozinha, especialidade, produto, necessidade).
Pedido: {q}"""

EXPAND_PROMPT = """Reescreva o pedido de um usuário como uma consulta de busca curta (até 25 palavras, português) para achar negócios numa base de recomendações: diga o tipo de lugar ou serviço e inclua sinônimos e variações que a ficha do negócio provavelmente usa. Sem nomes de pessoas. Responda em JSON: {{"query": "..."}}
Pedido: {q}"""

RERANK_PROMPT = """Um usuário pede indicações: "{q}"
Candidatos (id | nome | tipo > subcategoria | descrição | votos):
{items}
Escolha até {n} candidatos que realmente respondem ao pedido (o tipo certo de negócio ou produto), do mais ao menos adequado. Exclua os que não servem, mesmo que sobrem menos de {n}. Responda em JSON: {{"ids": [ids em ordem]}}"""

RERANK_VOTES_PROMPT = (
    RERANK_PROMPT
    + "\nEntre candidatos igualmente adequados, prefira o de melhor saldo de votos (primeiro número = 👍, segundo = 👎)."
)

RERANK_VARIETY_PROMPT = """Um usuário faz um pedido amplo: "{q}"
Candidatos (id | nome | tipo > subcategoria | descrição | votos 👍/👎):
{items}
Monte uma lista de até {n} indicações que sirva de panorama: cubra tipos variados (não repita o mesmo tipo seguidamente), priorize os de melhor saldo de votos e exclua os que não correspondem ao pedido. Responda em JSON: {{"ids": [ids em ordem]}}"""

FAMILY = {
    "Shops": "commerce",
    "Products": "commerce",
    "Markets & Groceries": "commerce",
    "Doctors": "health",
    "Dentists": "health",
}


def same_family(a: str, b: str) -> bool:
    return a == b or (a in FAMILY and FAMILY.get(a) == FAMILY.get(b))


JUDGE_PROMPT = """Você avalia a resposta de um assistente que recomenda negócios a brasileiros em Grenoble. Pergunta do usuário: "{q}"
Lista devolvida (nome | tipo > subcategoria | descrição | votos):
{items}
Responda em JSON:
{{"relevant": [true/false para cada item, na ordem: o item responde ao que foi pedido?],
 "usefulness": 1 a 5 (a lista, como resposta curta de WhatsApp, resolve o pedido?),
 "variety": 1 a 5 (os itens cobrem opções diferentes em vez de repetir o mesmo tipo; dê 3 se o pedido é muito específico),
 "note": "uma frase"}}"""


async def main_async(
    split: str, only: Optional[List[str]], broad: bool = False
) -> None:  # pragma: no cover - network
    import httpx
    from dotenv import load_dotenv

    from habitantes.domain.tools._embedding import _embed_texts
    from ingestion.config import settings
    from ingestion.suggestions.llm import chat_json
    from tests.eval.suggestions_retrieval import (
        load_dataset,
        names_match,
        split_dataset,
    )

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    d = Path(__file__).resolve().parents[2] / "artifacts/chat-19012021-02102026"
    gs = load_businesses(d)
    qs = split_dataset(load_dataset(), split)
    if broad:
        qs = [{"question": q, "expected": []} for q in BROAD_QUESTIONS]
    cfg = settings.suggestion_llm.model_copy(
        update={"model": "google/gemini-2.5-flash"}
    )
    cl = httpx.AsyncClient(timeout=120)

    def norm(M: np.ndarray) -> np.ndarray:
        return M / np.linalg.norm(M, axis=1, keepdims=True)

    E_raw = norm(np.array(_embed_texts([dense_text_raw(g) for g in gs])))
    E_v2 = norm(np.array(_embed_texts([dense_text_v2(g) for g in gs])))
    bm = BM25([keyword_text(g) for g in gs])
    Q = norm(np.array(_embed_texts([q["question"] for q in qs])))
    subs = "; ".join(
        f"{k.value}: {', '.join(v)}" for k, v in KIND_SUBCATEGORIES.items()
    )
    sem = asyncio.Semaphore(8)

    async def parse(q: str) -> Dict[str, Any]:
        async with sem:
            r = await chat_json(
                cl,
                PARSE_PROMPT.format(
                    kinds=", ".join(k.value for k in Kind), subs=subs, q=q
                ),
                cfg,
            )
        r = r or {}
        kind = r.get("kind") if r.get("kind") in {k.value for k in Kind} else ""
        sub = (
            r.get("subcategory")
            if kind and r.get("subcategory") in KIND_SUBCATEGORIES.get(Kind(kind), ())
            else ""
        )
        return {
            "kind": kind,
            "sub": sub,
            "terms": r.get("terms") or [],
            "broad": bool(r.get("broad")),
        }

    parsed = await asyncio.gather(*[parse(q["question"]) for q in qs])

    async def expand(q: str) -> str:
        async with sem:
            r = await chat_json(cl, EXPAND_PROMPT.format(q=q), cfg)
        return str((r or {}).get("query") or q)

    expanded = await asyncio.gather(*[expand(q["question"]) for q in qs])
    Q2 = norm(np.array(_embed_texts(expanded)))

    def rrf(ranks: List[np.ndarray], idx: np.ndarray) -> Dict[int, float]:
        sc: Dict[int, float] = collections.defaultdict(float)
        for order in ranks:
            for r, i in enumerate([i for i in order if i in set(idx.tolist())]):
                sc[int(i)] += 1 / (60 + r + 1)
        return sc

    def is_broad(qi: int) -> bool:
        return bool(parsed[qi]["broad"] and parsed[qi]["kind"])

    def rank(qi: int, text: str, strat: str) -> List[int]:
        p = parsed[qi]
        if strat == "X":  # routed: broad -> V, specific -> T
            return rank(qi, text, "V" if is_broad(qi) else "T")
        pool = np.arange(len(gs))
        if strat in "DEFGH" and p["kind"]:
            pool = np.array([i for i, g in enumerate(gs) if g["kind"] == p["kind"]])
            if strat in "EFGH" and p["sub"]:
                sp = np.array([i for i in pool if gs[i]["sub"] == p["sub"]])
                if len(sp) >= 3:
                    pool = sp
        E = E_raw if strat == "A" else E_v2
        qv = Q2[qi] if strat in "KMPQRSTW" else Q[qi]
        if strat in "IJ":
            sim = E_v2 @ Q[qi]
            boost = np.array(
                [
                    0.04 if p["kind"] and same_family(gs[i]["kind"], p["kind"]) else 0.0
                    for i in range(len(gs))
                ]
            )
            if strat == "I":
                return np.argsort(-(sim + boost))[:N].tolist()
            dense_order = np.argsort(-(sim + boost))
            kw = bm.scores(text + " " + " ".join(p["terms"]))
            kw_order = np.argsort(-(kw + 0.0))
            fused = rrf([dense_order, kw_order], pool)
            return sorted(fused, key=lambda i: -fused[i])[:N]
        dense = np.argsort(-(E[pool] @ qv))
        dense_order = pool[dense]
        if strat in "AB":
            return dense_order[:N].tolist()
        if strat in "KLMPQS":
            depth = {"K": N, "L": 25, "M": 25, "P": 15, "Q": 40, "S": 25}[strat]
            return dense_order[:depth].tolist()
        if strat in "UV" and p["kind"]:
            by: Dict[str, List[int]] = collections.defaultdict(list)
            for i, g in enumerate(gs):
                if g["kind"] == p["kind"] and g["sub"] and g["sub"] != "Outros":
                    by[g["sub"]].append(i)
            for sub_ in by:
                by[sub_].sort(key=lambda i: -gs[i]["q"])
            if by:
                if strat == "V":
                    return [i for v in by.values() for i in v[:4]]
                weights = {k: math.sqrt(len(v)) for k, v in by.items()}
                tot = sum(weights.values())
                alloc = {k: max(1, round(N * w_ / tot)) for k, w_ in weights.items()}
                while sum(alloc.values()) > N:
                    alloc[max(alloc, key=alloc.get)] -= 1
                return [
                    i
                    for k, n in sorted(alloc.items(), key=lambda kv: -kv[1])
                    for i in by[k][:n]
                ][:N]
        if strat in "UV":  # no Kind parsed: same candidates as T
            kw = bm.scores(expanded[qi] + " " + " ".join(p["terms"]))
            return list(
                dict.fromkeys(dense_order[:25].tolist() + np.argsort(-kw)[:25].tolist())
            )
        if strat in "RTW":
            depth = 15 if strat == "R" else 25
            kw = bm.scores(expanded[qi] + " " + " ".join(p["terms"]))
            return list(
                dict.fromkeys(
                    dense_order[:depth].tolist() + np.argsort(-kw)[:depth].tolist()
                )
            )
        kw = bm.scores(text + " " + " ".join(p["terms"]))
        kw_order = pool[np.argsort(-kw[pool])]
        fused = rrf([dense_order, kw_order], pool)
        order = sorted(fused, key=lambda i: -fused[i])
        if strat in "CDE":
            return order[:N]
        cand = order[:30]
        rel = np.array([fused[i] for i in cand])
        rel = (rel - rel.min()) / (rel.max() - rel.min() + 1e-9)
        qn = np.array([gs[i]["q"] for i in cand])
        qn = (qn - qn.min()) / (qn.max() - qn.min() + 1e-9)
        w = 0.5 if strat == "G" else 0.3
        blended = [cand[j] for j in np.argsort(-(rel * (1 - w) + qn * w))]
        if strat in "FG" or not (p["broad"] and p["kind"]):
            return blended[:N]
        by: Dict[str, List[int]] = collections.defaultdict(
            list
        )  # H: mix across subcategories
        for i in pool:
            if gs[i]["sub"] and gs[i]["sub"] != "Outros":
                by[gs[i]["sub"]].append(int(i))
        for s in by:
            by[s].sort(key=lambda i: -gs[i]["q"])
        if not by:
            return blended[:N]
        weights = {s: math.sqrt(len(v)) for s, v in by.items()}
        tot = sum(weights.values())
        alloc = {s: max(1, round(N * w_ / tot)) for s, w_ in weights.items()}
        while sum(alloc.values()) > N:
            alloc[max(alloc, key=alloc.get)] -= 1
        picks: List[int] = []
        for s, n in sorted(alloc.items(), key=lambda kv: -kv[1]):
            picks += by[s][:n]
        return picks[:N]

    STRATS = {
        "A": "dense, raw text",
        "B": "dense, rewritten text",
        "C": "hybrid (dense+BM25), rewritten",
        "D": "C + Kind filter from the question",
        "E": "D + subcategory filter when implied",
        "F": "E + quality blend (30%)",
        "G": "E + quality blend (50%)",
        "H": "F + mix across subcategories for broad requests",
        "I": "dense rewritten + soft Kind-family boost",
        "J": "hybrid rewritten + soft Kind-family boost",
        "K": "dense rewritten, question expanded into a search query",
        "L": "B + LLM re-rank of top 25",
        "M": "K + LLM re-rank of top 25",
        "P": "K + LLM re-rank of top 15",
        "Q": "K + LLM re-rank of top 40",
        "R": "K + hybrid candidates (15 dense + 15 BM25) + re-rank",
        "S": "M + re-rank prefers better votes",
        "U": "broad: quota mix across subcategories by quality (no LLM)",
        "V": "broad: top 4 per subcategory + LLM re-rank for variety",
        "X": "ROUTED: broad request -> V, specific request -> T",
        "W": "T candidates + variety instruction in the re-rank (for broad requests)",
        "T": "expanded query + hybrid candidates (25+25) + re-rank preferring votes",
    }
    keys = only or list(STRATS)
    lists = {s: [rank(qi, q["question"], s) for qi, q in enumerate(qs)] for s in keys}

    async def rerank(qi: int, cand: List[int], strat: str) -> List[int]:
        items = "\n".join(
            f"{i} | {gs[i]['group']} | {where(gs[i])} | {gs[i]['desc']} | {gs[i]['up']}/{gs[i]['down']}"
            for i in cand
        )
        async with sem:
            r = await chat_json(
                cl,
                (
                    RERANK_VARIETY_PROMPT
                    if strat in "VW" or (strat == "X" and is_broad(qi))
                    else RERANK_VOTES_PROMPT
                    if strat in "STX"
                    else RERANK_PROMPT
                ).format(q=qs[qi]["question"], items=items, n=N),
                cfg,
            )
        ids = [i for i in (r or {}).get("ids", []) if isinstance(i, int) and i in cand]
        return (list(dict.fromkeys(ids)) or cand)[:N]

    for s in [k for k in keys if k in "LMPQRSTVWX"]:
        lists[s] = list(
            await asyncio.gather(
                *[rerank(qi, lists[s][qi], s) for qi in range(len(qs))]
            )
        )

    async def judge(qi: int, s: str) -> Dict[str, Any]:
        items = "\n".join(
            f"{j + 1}. {gs[i]['group']} | {where(gs[i])} | {gs[i]['desc']} | {gs[i]['up']}👍/{gs[i]['down']}👎"
            for j, i in enumerate(lists[s][qi])
        )
        async with sem:
            r = await chat_json(
                cl, JUDGE_PROMPT.format(q=qs[qi]["question"], items=items), cfg
            )
        return r or {}

    judged = {
        s: await asyncio.gather(*[judge(qi, s) for qi in range(len(qs))]) for s in keys
    }
    print(
        f"split={split}: {len(qs)} questions, pool {len(gs)} businesses, N={N}; parse: Kind inferred for {sum(bool(p['kind']) for p in parsed)}/{len(qs)}, broad {sum(p['broad'] for p in parsed)}"
    )
    print(
        f"\n{'':2s}{'strategy':48s} recall@{N} hit | judge: precision usefulness variety"
    )
    summary = {}
    for s in keys:
        tot = hit = anyhit = 0
        prec, use, var = [], [], []
        for qi, q in enumerate(qs):
            names = [{gs[i]["group"], *gs[i]["names"]} for i in lists[s][qi]]
            for e in q["expected"]:
                tot += 1
                hit += any(names_match(e, n) for ns in names for n in ns)
            anyhit += any(
                names_match(e, n) for e in q["expected"] for ns in names for n in ns
            )
            j = judged[s][qi]
            rel = j.get("relevant") or []
            if rel:
                prec.append(sum(bool(x) for x in rel) / len(rel))
            if isinstance(j.get("usefulness"), (int, float)):
                use.append(j["usefulness"])
            if isinstance(j.get("variety"), (int, float)):
                var.append(j["variety"])
        m = lambda x: sum(x) / len(x) if x else 0.0  # noqa: E731
        summary[s] = (hit / max(tot, 1), m(prec), m(use), m(var))
        print(
            f"  {s} {STRATS[s]:48s} {hit / max(tot, 1):.2f}  {anyhit / len(qs):.0%} |        {m(prec):.2f}      {m(use):.2f}      {m(var):.2f}"
        )
    out = d / f"quality_gate/index_experiment_{split}.json"
    out.write_text(
        json.dumps(
            {
                "strategies": STRATS,
                "summary": summary,
                "parsed": parsed,
                "questions": [q["question"] for q in qs],
                "lists": {
                    s: [[gs[i]["group"] for i in row] for row in lists[s]] for s in keys
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
    p.add_argument(
        "--broad", action="store_true", help="broad requests (no expected names)"
    )
    p.add_argument("--only", nargs="*", help="strategy letters to run (default all)")
    a = p.parse_args()
    asyncio.run(main_async(a.split, a.only, a.broad))


if __name__ == "__main__":
    main()
