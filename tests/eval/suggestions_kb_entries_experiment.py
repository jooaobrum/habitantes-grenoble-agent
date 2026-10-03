"""Batch synthesis of 'question -> recommendation' entries per Kind (subset experiment).

An LLM reads a 30% stratified batch of a Kind's businesses together (descriptions, items,
votes, source messages) and writes entries: a question a newcomer would ask, a short
context grounded in the batch, and 2-6 recommended business IDs. It never writes names,
votes or dates: those are filled from our data by ID, so an entry cannot invent a business.

Checks: ID validity, coverage of the batch, duplicate questions / recommendation sets, and
retrieval of the dataset's expected names (restricted to the sampled businesses) compared
with plain business-level dense search over the same sampled businesses.
"""

from __future__ import annotations

import asyncio
import collections
import json
import random
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

SAMPLE_SHARE = 0.30
KINDS = ["Restaurants & Bars", "Places & Outings"]

GEN_PROMPT = """Você cria a base de conhecimento de recomendações de um assistente para brasileiros em Grenoble. Abaixo estão {n} negócios recomendados pela comunidade (tipo: {kind}). Analise TODOS juntos e crie entradas "pergunta -> recomendação".
Cada entrada:
- "question": pergunta natural que um recém-chegado faria no WhatsApp, em português; específica (cozinha, necessidade, produto, ocasião) ou ampla.
- "scope": "specific" ou "broad".
- "context": 1 a 2 frases resumindo o que a comunidade diz sobre essas opções; só fatos das fichas; sem inventar; sem citar mensagens nem pessoas.
- "ids": 2 a 6 ids (somente os ids abaixo) dos negócios que melhor respondem, do mais ao menos adequado; 1 id só se for único.
Regras: use cada negócio em ao menos uma entrada quando fizer sentido; não repita perguntas iguais ou quase iguais (se duas perguntas dariam as mesmas recomendações, una); entre 12 e 24 entradas; cubra tanto pedidos específicos quanto amplos.
Responda em JSON: {{"entries":[{{"question":"...","scope":"specific","context":"...","ids":[0,1]}}]}}

Negócios (id | nome | tipo > subcategoria | descrição | itens | votos 👍/👎 | o que membros escreveram):
{lines}"""


def render(entry: Dict[str, Any], batch: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Fill the ontology facts from data, by id. Unknown ids are dropped."""
    recs = []
    for i in entry["ids"]:
        if (
            isinstance(i, int)
            and 0 <= i < len(batch)
            and i not in [r["_i"] for r in recs]
        ):
            g = batch[i]
            recs.append(
                {
                    "_i": i,
                    "name": g["group"],
                    "kind": g["kind"],
                    "subcategory": g["sub"],
                    "thumbs_up": g["up"],
                    "thumbs_down": g["down"],
                    "last_date": g["last"],
                    "items": [x for x, _ in g["items"].most_common(3)],
                    "description": g["desc"],
                }
            )
    return {
        "question": entry["question"].strip(),
        "scope": entry.get("scope", ""),
        "context": entry.get("context", "").strip(),
        "recommendations": [{k: v for k, v in r.items() if k != "_i"} for r in recs],
    }


async def main_async() -> None:  # pragma: no cover - network
    import httpx
    from dotenv import load_dotenv

    from habitantes.domain.tools._embedding import _embed_texts
    from ingestion.config import settings
    from ingestion.suggestions.llm import chat_json
    from tests.eval.suggestions_index_experiment import dense_text_v2, load_businesses
    from tests.eval.suggestions_retrieval import (
        load_dataset,
        names_match,
        split_dataset,
    )

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    d = root / "artifacts/chat-19012021-02102026"
    gs = load_businesses(d)
    cfg = settings.suggestion_llm.model_copy(
        update={"model": "google/gemini-2.5-flash"}
    )
    cl = httpx.AsyncClient(timeout=180)
    rng = random.Random(5)

    batches: Dict[str, List[Dict[str, Any]]] = {}
    for kind in KINDS:
        pool = [g for g in gs if g["kind"] == kind]
        by = collections.defaultdict(list)
        for g in pool:
            by[g["sub"]].append(g)
        pick: List[Dict[str, Any]] = []
        for (
            sub,
            members,
        ) in by.items():  # stratified: the same share from each subcategory
            k = max(1, round(len(members) * SAMPLE_SHARE))
            pick += rng.sample(members, min(k, len(members)))
        batches[kind] = pick

    async def gen(kind: str) -> List[Dict[str, Any]]:
        batch = batches[kind]
        lines = "\n".join(
            f"{i} | {g['group']} | {g['kind']} > {g['sub']} | {g['desc']} | {', '.join(x for x, _ in g['items'].most_common(4))} | {g['up']}/{g['down']} | "
            + " // ".join(m[:160] for m in g["msgs"][:2])
            for i, g in enumerate(batch)
        )
        res = await chat_json(
            cl, GEN_PROMPT.format(n=len(batch), kind=kind, lines=lines), cfg
        )
        return [
            render(e, batch)
            for e in (res or {}).get("entries", [])
            if isinstance(e.get("ids"), list) and e.get("question")
        ]

    entries: Dict[str, List[Dict[str, Any]]] = {}
    for kind in KINDS:
        entries[kind] = await gen(kind)
    flat = [(k, e) for k, es in entries.items() for e in es if e["recommendations"]]
    out = d / "quality_gate/kb_entries_subset.jsonl"
    out.write_text(
        "".join(
            json.dumps({"kind": k, **e}, ensure_ascii=False) + "\n" for k, e in flat
        )
    )

    print("SUBSET:", {k: f"{len(batches[k])} businesses sampled" for k in KINDS})
    for kind in KINDS:
        es = [e for e in entries[kind] if e["recommendations"]]
        used = collections.Counter(r["name"] for e in es for r in e["recommendations"])
        sets = [frozenset(r["name"] for r in e["recommendations"]) for e in es]
        dup_sets = len(sets) - len(set(sets))
        print(
            f"\n{kind}: {len(es)} entries | businesses covered {len(used)}/{len(batches[kind])} ({len(used) / len(batches[kind]):.0%}) | identical recommendation sets: {dup_sets} | avg recs/entry {sum(len(e['recommendations']) for e in es) / max(1, len(es)):.1f} | broad {sum(e['scope'] == 'broad' for e in es)}"
        )

    # retrieval: user questions vs synthesized questions, expected names restricted to the sampled businesses
    sampled = {g["group"]: g for ks in batches.values() for g in ks}
    tuned = split_dataset(load_dataset(), "tune")
    rows = []
    for q in tuned:
        exp = [
            e
            for e in q["expected"]
            if any(
                names_match(e, n)
                for g in sampled.values()
                for n in g["names"] | {g["group"]}
            )
        ]
        if exp:
            rows.append((q, exp))
    print(
        f"\ntune questions with >=1 expected name among the sampled businesses: {len(rows)}"
    )
    if rows and flat:

        def norm(M: np.ndarray) -> np.ndarray:
            return M / np.linalg.norm(M, axis=1, keepdims=True)

        Qm = norm(np.array(_embed_texts([q["question"] for q, _ in rows])))
        variants = {
            "entry question only": lambda e: e["question"],
            "question + context": lambda e: f"{e['question']} {e['context']}",
            "question + context + names": lambda e: (
                f"{e['question']} {e['context']} "
                + ", ".join(r["name"] for r in e["recommendations"])
            ),
        }
        samp = list(sampled.values())
        Eb = norm(np.array(_embed_texts([dense_text_v2(g) for g in samp])))
        print(
            f"{'approach':46s} recall (expected names reachable, top3 entries -> up to 8 names)"
        )
        for name, fn in variants.items():
            Ee = norm(np.array(_embed_texts([fn(e) for _, e in flat])))
            hit = tot = 0
            for qi, (q, exp) in enumerate(rows):
                order = np.argsort(-(Ee @ Qm[qi]))[:3]
                names: List[str] = []
                for oi in order:
                    for r in flat[oi][1]["recommendations"]:
                        if r["name"] not in names:
                            names.append(r["name"])
                names = names[:8]
                for e_ in exp:
                    tot += 1
                    hit += any(names_match(e_, n) for n in names)
            print(f"  KB entries, {name:30s} {hit / max(tot, 1):.2f}  ({hit}/{tot})")
        hit = tot = 0
        for qi, (q, exp) in enumerate(rows):
            order = np.argsort(-(Eb @ Qm[qi]))[:8]
            names = [samp[i]["group"] for i in order]
            for e_ in exp:
                tot += 1
                hit += any(names_match(e_, n) for n in names)
        print(
            f"  business-level dense (B), same sampled businesses   {hit / max(tot, 1):.2f}  ({hit}/{tot})"
        )
    print("\nEXAMPLE ENTRIES:")
    for k, e in random.Random(1).sample(flat, min(8, len(flat))):
        print(
            f"\n  [{k}] Q: {e['question']}  ({e['scope']})\n    context: {e['context']}"
        )
        for r in e["recommendations"]:
            print(
                f"    - {r['name']} [{r['subcategory']}] {r['thumbs_up']}👍/{r['thumbs_down']}👎, última {r['last_date']}, itens {r['items'][:2]}"
            )
    print("\nsaved", out)


def main() -> None:  # pragma: no cover
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
