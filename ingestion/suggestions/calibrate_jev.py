"""Calibrate the Jev window gate (cutoff and question wording) on a sample.

Proxy ground truth: a stronger LLM answers the same yes/no question on each
sampled window. Jev's P(yes) is then compared with it for several question
wordings, and a cutoff is picked that keeps recall high (a missed window loses
Suggestions for good, while a false positive only costs one extraction call).
The proxy labels are model output, not hand labels: check a few by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from ingestion.suggestions.windows import Window, is_request

LABEL_PROMPT = """Abaixo está um trecho de um grupo de WhatsApp de brasileiros em \\
Grenoble (autores anonimizados). Ele contém ao menos uma SUGESTÃO? Sugestão = um \\
membro indica, recomenda ou critica (opinião positiva ou negativa, mesmo casual, \\
sem pergunta) um negócio, lugar, profissional ou produto ESPECÍFICO e nomeado \\
(loja, restaurante, médico, serviço, marca...). Não contam: pedidos sem resposta \\
com nome, bancos, operadoras, apps, órgãos públicos, pessoas físicas, eventos \\
pontuais. Responda em JSON: {{"has_suggestion": true/false}}

TRECHO:
{text}"""

# Wordings tried against the proxy labels (`default` is the production wording).
VARIANTS: Dict[str, Optional[str]] = {
    "default": None,  # WINDOW_QUESTION in ingestion/preprocess/jev.py (answer-focused)
    "previous": (
        "Does this excerpt of a group chat contain a Suggestion: a "
        "member giving a positive or negative opinion about a specific "
        "business, place or product (a shop, restaurant, doctor, "
        "service...)? Questions alone, banks, phone operators, apps "
        "and public services do not count."
    ),
    "inclusive": (
        "Does this excerpt of a group chat mention, recommend or criticise any "
        "specific named business, place, professional or product (a shop, "
        "supermarket, restaurant, doctor, service, brand...), even casually and "
        "even only as an answer to someone's question? Names of banks, phone "
        "operators, apps and public services do not count."
    ),
}


def sample_windows(windows: List[Window], n: int, seed: int) -> List[Window]:
    """Half request-opened and half other windows, seeded."""
    rng = random.Random(seed)
    req = [w for w in windows if is_request(str(w.messages[0].get("message", "")))]
    other = [w for w in windows if w not in req]
    half = n // 2
    return rng.sample(req, min(half, len(req))) + rng.sample(
        other, min(n - half, len(other))
    )


def metrics(
    rows: List[Dict[str, Any]], variant: str, cutoff: float
) -> Dict[str, float]:
    tp = fp = fn = tn = 0
    for r in rows:
        s = r["scores"].get(variant)
        if s is None:
            continue
        pred, truth = s >= cutoff, r["truth"]
        tp += pred and truth
        fp += pred and not truth
        fn += (not pred) and truth
        tn += (not pred) and not truth
    return {
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "pass_rate": (tp + fp) / max(1, tp + fp + fn + tn),
    }


def best_cutoff(
    rows: List[Dict[str, Any]], variant: str, min_recall: float = 0.9
) -> Optional[float]:
    """Highest cutoff (cheapest gate) that still reaches `min_recall`."""
    best = None
    for c in [i / 100 for i in range(1, 100)]:
        if metrics(rows, variant, c)["recall"] >= min_recall:
            best = c
    return best


def main() -> None:  # pragma: no cover - needs network
    import httpx

    from ingestion.config import settings
    from ingestion.preprocess.jev import score_window
    from ingestion.suggestions.extract import pseudonymise
    from ingestion.suggestions.labelling import load_classified
    from ingestion.suggestions.llm import chat_json
    from ingestion.suggestions.windows import build_windows

    root = Path(__file__).parents[2]
    default_csv = (
        root
        / settings.artifacts_dir
        / Path(settings.input_file).stem
        / "classified.csv"
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=default_csv)
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--label-model", default="google/gemini-2.5-flash")
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()

    sug = settings.suggestions
    windows = build_windows(
        load_classified(args.input),
        settings.qa.thread_gap_h,
        sug.window_before,
        sug.window_after_request,
        sug.window_after_other,
    )
    sample = sample_windows(windows, args.n, args.seed)
    label_cfg = settings.suggestion_llm.model_copy(update={"model": args.label_model})

    async def run() -> List[Dict[str, Any]]:
        sem = asyncio.Semaphore(8)
        client = httpx.AsyncClient()

        async def one(w: Window) -> Dict[str, Any]:
            text, _ = pseudonymise(w)
            async with sem:
                lab = await chat_json(client, LABEL_PROMPT.format(text=text), label_cfg)
                scores = {}
                for name, q in VARIANTS.items():
                    kw = {"question": q} if q else {}
                    scores[name] = await score_window(
                        client,
                        text,
                        model=settings.jev.model,
                        base_url=settings.jev.base_url,
                        max_retries=settings.jev.max_retries,
                        retry_base_sleep_s=settings.jev.retry_base_sleep_s,
                        **kw,
                    )
            return {
                "thread_id": w.thread_id,
                "request": is_request(str(w.messages[0].get("message", ""))),
                "text": text,
                "truth": bool(lab and lab.get("has_suggestion")),
                "scores": scores,
            }

        return list(await asyncio.gather(*[one(w) for w in sample]))

    rows = asyncio.run(run())
    out = args.output or args.input.parent / "jev_calibration.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    pos = sum(r["truth"] for r in rows)
    print(f"{len(rows)} windows, {pos} proxy-positive ({pos / len(rows):.0%}) -> {out}")
    print(f"current cutoff {sug.jev_cutoff}:")
    for v in VARIANTS:
        cur = metrics(rows, v, sug.jev_cutoff)
        bc = best_cutoff(rows, v)
        at = metrics(rows, v, bc) if bc is not None else None
        print(
            f"  {v:15s} recall={cur['recall']:.2f} precision={cur['precision']:.2f} "
            f"pass={cur['pass_rate']:.2f} | best cutoff for recall>=0.9: {bc} "
            + (
                f"(precision={at['precision']:.2f} pass={at['pass_rate']:.2f})"
                if at
                else ""
            )
        )


if __name__ == "__main__":
    main()
