"""Assign one subcategory to each filtered group, as a separate pass (no re-extraction).

Context per group: name, Kind, items, the extracted Context, and up to two source messages
(what members actually wrote, recovered by `source_messages.py`). The vocabulary and the
one-line definitions are the same ones the extraction prompt uses
(`habitantes.domain.suggestions.SUBCATEGORY_GUIDE`), so a future extraction run and this
pass agree. Kinds without subcategories (Housing) get none.

Output: `grouped_mentions_filtered_subcategory.jsonl` (every row of the filtered file plus
`subcategory`, the group's) and `groups_filtered.jsonl` (one line per group).
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from habitantes.domain.suggestions import (
    KIND_SUBCATEGORIES,
    Kind,
    subcategory_guide_text,
)

BATCH = 20
ASSIGN_PROMPT = """Você classifica negócios citados num grupo de WhatsApp de brasileiros em Grenoble. Tipo (kind): "{kind}".
Subcategorias (formato "nome: definição"):
{guide}
Escolha UMA para cada negócio e responda SÓ com o NOME (o texto antes dos dois-pontos), um destes: {names}.
Decida pelo nome, pelos itens e principalmente pelo que os membros escreveram. Se nada servir, use "Outros" quando existir; senão a mais próxima.
Responda em JSON: {{"r":[{{"i":n,"s":"nome da subcategoria"}}]}}

Negócios (nome | itens | o que membros escreveram):
{lines}"""

Chat = Callable[..., Awaitable[Optional[Dict[str, Any]]]]


def answer_schema(allowed: tuple) -> Dict[str, Any]:
    """JSON schema that only lets the model answer with one of the Kind's subcategories."""
    return {
        "name": "subcategories",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["r"],
            "properties": {
                "r": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["i", "s"],
                        "properties": {
                            "i": {"type": "integer"},
                            "s": {"type": "string", "enum": list(allowed)},
                        },
                    },
                }
            },
        },
    }


def group_line(i: int, g: Dict[str, Any]) -> str:
    said = " // ".join(m[:240] for m in g["messages"][:2]) or g.get("context", "")[:200]
    return f"{i}. {g['group']} | {', '.join(g['items'][:4])} | {said}"


def build_prompt(kind: str, groups: List[Dict[str, Any]]) -> str:
    return ASSIGN_PROMPT.format(
        kind=kind,
        guide=subcategory_guide_text(kind),
        names=json.dumps(
            list(KIND_SUBCATEGORIES.get(Kind(kind), ())), ensure_ascii=False
        ),
        lines="\n".join(group_line(i, g) for i, g in enumerate(groups)),
    )


def build_group_records(
    rows: List[Dict[str, Any]], sources: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """One record per group: name, kind, counts, items, a context and source messages."""
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)
    out = []
    for name, rs in by.items():
        items = Counter(i for r in rs for i in r["items"])
        out.append(
            {
                "group": name,
                "kind": Counter(r["kind"] for r in rs).most_common(1)[0][0],
                "mentions": len(rs),
                "items": [i for i, _ in items.most_common(5)],
                "context": rs[0]["context"],
                "messages": (sources.get(name) or {}).get("messages", []),
            }
        )
    return out


async def assign(
    records: List[Dict[str, Any]],
    chat: Chat,
    cfg: Any,
    client: Any,
    concurrency: int = 8,
) -> Dict[str, Optional[str]]:
    """group -> subcategory (None when the Kind has none or the model gave no valid answer)."""
    sem = asyncio.Semaphore(concurrency)
    result: Dict[str, Optional[str]] = {r["group"]: None for r in records}
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_kind[r["kind"]].append(r)

    async def one(kind: str, chunk: List[Dict[str, Any]]) -> None:
        allowed = KIND_SUBCATEGORIES.get(Kind(kind), ())
        async with sem:
            data = await chat(
                client, build_prompt(kind, chunk), cfg, schema=answer_schema(allowed)
            )
        for item in (data or {}).get("r", []):
            i, s = item.get("i"), item.get("s")
            if isinstance(i, int) and 0 <= i < len(chunk) and s in allowed:
                result[chunk[i]["group"]] = s

    jobs = [
        one(kind, rs[i : i + BATCH])
        for kind, rs in by_kind.items()
        if KIND_SUBCATEGORIES.get(Kind(kind))
        for i in range(0, len(rs), BATCH)
    ]
    await asyncio.gather(*jobs)
    # One retry, in smaller batches, for groups whose batch failed or came back invalid.
    retry: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        if result[r["group"]] is None and KIND_SUBCATEGORIES.get(Kind(r["kind"])):
            retry[r["kind"]].append(r)
    await asyncio.gather(
        *[
            one(kind, rs[i : i + 5])
            for kind, rs in retry.items()
            for i in range(0, len(rs), 5)
        ]
    )
    return result


def apply_subcategories(
    rows: List[Dict[str, Any]], subcategories: Dict[str, Optional[str]]
) -> List[Dict[str, Any]]:
    """Rows with the group's `subcategory` (a copy; nothing else changes)."""
    return [{**r, "subcategory": subcategories.get(r["group"])} for r in rows]


def main() -> None:  # pragma: no cover - needs LLM access
    """`python ingestion/suggestions/subcategory.py <chat artifacts dir>`."""
    import argparse

    import httpx
    from dotenv import load_dotenv

    from ingestion.config import settings
    from ingestion.suggestions.llm import chat_json

    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("dir", type=Path)
    p.add_argument("--model", default="google/gemini-2.5-flash")
    args = p.parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    rows = [
        json.loads(line) for line in open(args.dir / "grouped_mentions_filtered.jsonl")
    ]
    src_path = args.dir / "quality_gate" / "source_messages.jsonl"
    sources = (
        {json.loads(line)["group"]: json.loads(line) for line in open(src_path)}
        if src_path.exists()
        else {}
    )
    records = build_group_records(rows, sources)
    cfg = settings.suggestion_llm.model_copy(update={"model": args.model})

    async def run() -> Dict[str, Optional[str]]:
        return await assign(records, chat_json, cfg, httpx.AsyncClient(timeout=120))

    subs = asyncio.run(run())
    out = args.dir / "grouped_mentions_filtered_subcategory.jsonl"
    out.write_text(
        "".join(
            json.dumps(r, ensure_ascii=False) + "\n"
            for r in apply_subcategories(rows, subs)
        ),
        encoding="utf-8",
    )
    groups = args.dir / "groups_filtered.jsonl"
    groups.write_text(
        "".join(
            json.dumps(
                {k: r[k] for k in ("group", "kind", "mentions", "items")}
                | {"subcategory": subs[r["group"]]},
                ensure_ascii=False,
            )
            + "\n"
            for r in records
        ),
        encoding="utf-8",
    )
    n_unassigned = sum(
        1
        for r in records
        if KIND_SUBCATEGORIES.get(Kind(r["kind"])) and subs[r["group"]] is None
    )
    print(
        f"{len(rows)} rows, {len(records)} groups -> {out}; unassigned (with subcategories): {n_unassigned}"
    )


if __name__ == "__main__":
    main()
