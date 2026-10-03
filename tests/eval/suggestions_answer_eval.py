"""Answer-level eval for recommendation questions (Suggestions feature).

Runs the real agent end to end on each question of suggestions_pseudo_golden.tsv and
scores the FINAL ANSWER (not retrieval). All scoring is deterministic (regex + the
same `names_match` used by suggestions_retrieval.py); no LLM judge is used.

Per question:
  coverage : fraction of expected names present in the answer (reported only: the
             expected lists are partial pseudo-labels, so 100% is not the goal)
  hit      : coverage > 0 (>= 1 expected name present)
  checks   : structural / ontology checks from the PRD (see `structural_checks`);
             for a web-fallback answer with no community list, the four community
             format checks (counts, date, context, summary notice) are waived
  halluc   : answer items that appear in neither the tool results (suggestions,
             web, KB chunks) nor the question (see `faithfulness`)

PASS RULE (exact): passed = hit AND all structural checks pass AND hallucinations == 0.

Structural checks (each True = ok):
  has_counts        every listed item shows 👍 and 👎 counts, at least one item
  has_date          every listed item carries a date (dd/mm/yyyy, mm/yyyy or yyyy-mm-dd)
  has_context       every listed item has >= 3 words of context beyond name/counts/date
  summary_notice    says these are a summary / top picks / not exhaustive
  availability      reminds to confirm availability / hours
  disclosure        a flagged Community Business shown in the answer is disclosed
                    (n/a -> ok when the tool output shows none, or no tool output)
  no_quotes         no quoted member text and no "member said ..." attribution
  negatives_counts  no negative-opinion wording (negatives only as 👎 counts)
  no_net_negative   no item with more 👎 than 👍
  short             <= MAX_WORDS words and <= MAX_LINES non-empty lines
  no_weird_ask      <= 1 question mark and no request for personal data

Distractors (--probes): a non-recommendation message must NOT go down the suggestions
path: intent not in {recommendation, both}, no search_suggestions call, no 👍 counts.

Usage (needs Qdrant + keys):
  PYTHONPATH=.:api/src uv run python tests/eval/suggestions_answer_eval.py \
      --split tune --out /tmp/v2_tune.json
"""

from __future__ import annotations

import argparse
import contextlib
import contextvars
import json
import re
import statistics
import sys
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from suggestions_retrieval import (  # noqa: E402
    DEFAULT_TSV,
    load_dataset,
    names_match,
    norm,
    split_dataset,
)

MAX_WORDS = 220
MAX_LINES = 28
UP, DOWN = "\U0001f44d", "\U0001f44e"
COMMUNITY_FLAG = "divulgação própria"

DATE_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{4}\b|\b\d{1,2}/\d{4}\b|\b\d{4}-\d{2}(-\d{2})?\b"
)
UP_RE = re.compile(rf"(\d+)\s*{UP}|{UP}\s*(\d+)")
DOWN_RE = re.compile(rf"(\d+)\s*{DOWN}|{DOWN}\s*(\d+)")
BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
SUMMARY_RE = re.compile(
    r"resumo|principais|n[ãa]o\s+(é|e|se trata de|sou)\s+(uma\s+)?lista\s+exaustiva|"
    r"lista\s+exaustiva|nem\s+todas|algumas\s+(das\s+)?(indica|sugest)|mais\s+citad|"
    r"mais\s+indicad|destaques",
    re.I,
)
AVAIL_RE = re.compile(
    r"confirm\w*[^.\n]{0,60}(disponibilidade|hor[áa]rio|funcionamento|abert)|"
    r"(disponibilidade|hor[áa]rios?)[^.\n]{0,60}confirm",
    re.I,
)
QUOTE_RE = re.compile(r"[\"“«]([^\"”»]*(?:\s[^\"”»\s]+){3,}[^\"”»]*)[\"”»]")
ATTRIB_RE = re.compile(
    r"\b(membro|participante|pessoa|algu[ée]m|usu[áa]rio|morador)\w*\s+"
    r"(do grupo\s+)?(disse|falou|comentou|afirmou|relatou|escreveu|contou)|"
    r"\bsegundo\s+(o|a)\s+(membro|participante)|"
    r"\b(disse|falou|comentou)\s+que\b",
    re.I,
)
NEGATIVE_RE = re.compile(
    r"p[ée]ssim|\bruim\b|ruins|decepcion|reclama|\bcr[ií]tica|evite|cuidado com|"
    r"n[ãa]o recomend|mau atendimento|atendimento ruim|caro demais|n[ãa]o gostaram|"
    r"insatisf",
    re.I,
)
PERSONAL_ASK_RE = re.compile(
    r"(seu|sua)\s+(nome|telefone|e-?mail|endere[çc]o|cpf|passaporte|n[úu]mero)", re.I
)
STRUCTURAL_LEADS = {
    "lembrete", "observacao", "nota", "importante", "resumo", "dica", "aviso",
    "atencao", "obs", "fonte", "fontes", "total", "endereco", "telefone",
    "telefones", "horario", "horarios", "site", "preco", "precos", "url", "https", "contato",
    "http",
}  # fmt: skip


DOMAIN_RE = re.compile(r"\w\.(fr|com|org|net|io|eu)\b")
ARTICLES = {"o", "a", "os", "as", "um", "uma", "no", "na"}


def _fold(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    )


# ── answer parsing ───────────────────────────────────────────────────────────


def _item_name(line_body: str) -> str:
    """Name of a listed item: bold span if any, else the text before : – — ( |."""
    m = BOLD_RE.search(line_body)
    if m:
        return m.group(1).strip(" :-–—")
    head = re.split(r"\s[–—-]\s|[:(|,]|\d+\s*" + UP, line_body, maxsplit=1)[0]
    return head.strip(" *_:-–—")


def parse_items(answer: str) -> list[dict[str, Any]]:
    """Bullet lines of the answer as items (name, counts, date, context words)."""
    items = []
    for raw in (answer or "").splitlines():
        m = BULLET_RE.match(raw)
        if not m:
            continue
        body = m.group(1)
        name = _item_name(body)
        if not name or len(name.split()) > 7:
            continue
        up = UP_RE.search(body)
        down = DOWN_RE.search(body)
        rest = BOLD_RE.sub(" ", body, count=1) if BOLD_RE.search(body) else body
        rest = rest.replace(name, " ", 1)
        rest = DATE_RE.sub(" ", UP_RE.sub(" ", DOWN_RE.sub(" ", rest)))
        rest = re.sub(r"[^\w\s]", " ", rest)
        items.append(
            {
                "name": name,
                "line": body,
                "has_up": bool(up),
                "has_down": bool(down),
                "up": int(next(g for g in up.groups() if g)) if up else None,
                "down": int(next(g for g in down.groups() if g)) if down else None,
                "has_date": bool(DATE_RE.search(body)),
                "context_words": len(rest.split()),
            }
        )
    return items


def listed_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items that are recommendation entries (carry community counts)."""
    return [i for i in items if i["has_up"] or i["has_down"]]


def expected_present(expected: list[str], answer: str, items: list[dict]) -> list[str]:
    na = " " + norm(answer) + " "
    out = []
    for e in expected:
        ne = norm(e)
        if any(names_match(e, i["name"]) for i in items) or (ne and f" {ne} " in na):
            out.append(e)
    return out


# ── tool output helpers ──────────────────────────────────────────────────────


def tool_members(suggestion_outputs: list[str]) -> list[dict[str, Any]]:
    """Members named in `search_suggestions` output (name, community_business flag)."""
    members = []
    for text in suggestion_outputs:
        for line in text.splitlines():
            m = re.match(r"^- \**(.+?)\**(?: \[([^\]]+)\])?(?::| —) \d+" + UP, line)
            if m:
                members.append(
                    {"name": m.group(1).strip(), "community": bool(m.group(2))}
                )
    return members


# ── scoring functions ────────────────────────────────────────────────────────


def structural_checks(
    answer: str, members: list[dict[str, Any]] | None = None
) -> dict[str, bool]:
    items = parse_items(answer)
    listed = listed_items(items)
    lines = [ln for ln in (answer or "").splitlines() if ln.strip()]
    community = [m["name"] for m in (members or []) if m["community"]]
    shown_community = [
        c for c in community if any(names_match(c, i["name"]) for i in items)
    ]
    return {
        "has_counts": bool(listed)
        and all(i["has_up"] and i["has_down"] for i in listed),
        "has_date": bool(listed) and all(i["has_date"] for i in listed),
        "has_context": bool(listed) and all(i["context_words"] >= 3 for i in listed),
        "summary_notice": bool(SUMMARY_RE.search(answer or "")),
        "availability": bool(AVAIL_RE.search(answer or "")),
        "disclosure": (not shown_community)
        or bool(
            re.search(
                r"divulga|membro do grupo|neg[óo]cio de membro",
                _fold(answer) + (answer or ""),
                re.I,
            )
        ),
        "no_quotes": not QUOTE_RE.search(answer or "")
        and not ATTRIB_RE.search(answer or ""),
        "negatives_counts": not NEGATIVE_RE.search(answer or ""),
        "no_net_negative": not any(
            i["up"] is not None and i["down"] is not None and i["down"] > i["up"]
            for i in listed
        ),
        "short": len((answer or "").split()) <= MAX_WORDS and len(lines) <= MAX_LINES,
        "no_weird_ask": (answer or "").count("?") <= 1
        and not PERSONAL_ASK_RE.search(answer or ""),
    }


def faithfulness(answer: str, question: str, corpus: list[str]) -> list[str]:
    """Names listed in the answer that are in neither the tool output nor the question.

    Candidates are bullet-lead / bold names. A candidate is grounded when all its
    normalised tokens occur in the normalised corpus (tool outputs: suggestions, web,
    KB chunks) or in the question.
    """
    pool = set(norm(" ".join(corpus + [question])).split())
    bad = []
    for it in parse_items(answer):
        folded = _fold(it["name"]).strip(" ")
        if (
            folded in STRUCTURAL_LEADS
            or DOMAIN_RE.search(folded)  # a site address, not a business name
            or folded.split()[0] in ARTICLES  # "O botão de pressão": a heading
        ):
            continue
        toks = norm(it["name"]).split()
        if not toks:
            continue
        if not all(t in pool for t in toks):
            bad.append(it["name"])
    return bad


COMMUNITY_FORMAT_CHECKS = ("has_counts", "has_date", "has_context", "summary_notice")


def waive_web_fallback(
    checks: dict[str, bool], items: list[dict], web_outputs: list[str] | None
) -> None:
    """Web fallback (the community had nothing usable): the community-picks format
    (counts, dates, one-line context, summary notice) does not apply."""
    if web_outputs and not listed_items(items):
        for name in COMMUNITY_FORMAT_CHECKS:
            checks[name] = True


def score_case(
    case: dict[str, Any],
    answer: str,
    suggestion_outputs: list[str],
    corpus: list[str],
    web_outputs: list[str] | None = None,
) -> dict[str, Any]:
    items = parse_items(answer)
    present = expected_present(case["expected"], answer, items)
    members = tool_members(suggestion_outputs)
    checks = structural_checks(answer, members)
    waive_web_fallback(checks, items, web_outputs)
    halluc = faithfulness(answer, case["question"], corpus)
    hit = bool(present)
    return {
        "present": present,
        "coverage": len(present) / len(case["expected"]) if case["expected"] else 0.0,
        "hit": hit,
        "checks": checks,
        "structural_ok": all(checks.values()),
        "hallucinations": halluc,
        "passed": hit and all(checks.values()) and not halluc,
        "words": len((answer or "").split()),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0}
    check_names = list(rows[0]["checks"])
    return {
        "n": n,
        "hit_rate": round(sum(r["hit"] for r in rows) / n, 3),
        "mean_coverage": round(statistics.mean(r["coverage"] for r in rows), 3),
        "pass_rate": round(sum(r["passed"] for r in rows) / n, 3),
        "structural_ok_rate": round(sum(r["structural_ok"] for r in rows) / n, 3),
        "hallucinated_names": sum(len(r["hallucinations"]) for r in rows),
        "answers_with_hallucination": sum(bool(r["hallucinations"]) for r in rows),
        "avg_words": round(statistics.mean(r["words"] for r in rows), 1),
        "checks": {
            c: round(sum(r["checks"][c] for r in rows) / n, 3) for c in check_names
        },
    }


def distractor_ok(intent: str | None, answer: str, suggestion_calls: int) -> bool:
    return (
        intent not in ("recommendation", "both")
        and suggestion_calls == 0
        and UP not in (answer or "")
    )


# ── running the agent ────────────────────────────────────────────────────────

_REC: contextvars.ContextVar[dict | None] = contextvars.ContextVar("rec", default=None)


@contextlib.contextmanager
def recording_tools():
    """Patch search_clusters / web_search so every tool result is captured per call."""
    patches = []

    def wrap(module, attr, kind):
        orig = getattr(module, attr)

        def inner(*a, **kw):
            res = orig(*a, **kw)
            rec = _REC.get()
            if rec is not None and isinstance(res, dict):
                text = res.get("formatted")
                if text is None and "results" in res:
                    text = "\n".join(
                        f"{r.get('title', '')} {r.get('content', '')}"
                        for r in res["results"]
                    )
                rec[kind].append(text or "")
            return res

        setattr(module, attr, inner)
        patches.append((module, attr, orig))

    try:
        from habitantes.domain.tools import suggestions as sug_mod

        wrap(sug_mod, "search_clusters", "suggestions")
    except ImportError:  # v1 bot: no suggestions path
        pass
    from habitantes.domain.tools import web_search as web_mod

    wrap(web_mod, "web_search", "web")
    try:
        yield
    finally:
        for module, attr, orig in patches:
            setattr(module, attr, orig)


def run_agent(question: str) -> dict[str, Any]:
    from habitantes.domain import agent as agent_mod

    rec: dict[str, list[str]] = {"suggestions": [], "web": []}
    token = _REC.set(rec)
    try:
        state = agent_mod.run(
            chat_id=f"ans-{uuid.uuid4().hex[:8]}",
            message=question,
            message_id=uuid.uuid4().hex,
            trace_id=uuid.uuid4().hex,
        )
        err = None
    except Exception as exc:  # keep the run going; the case fails
        state, err = {}, repr(exc)
    finally:
        _REC.reset(token)
    kb = [c.get("text", "") for c in state.get("context_chunks", []) or []]
    return {
        "answer": state.get("answer", "") or "",
        "intent": state.get("intent"),
        "suggestion_outputs": rec["suggestions"],
        "web_outputs": rec["web"],
        "kb_texts": kb,
        "error": err or state.get("error"),
    }


def eval_case(case: dict[str, Any]) -> dict[str, Any]:
    run = run_agent(case["question"])
    corpus = run["suggestion_outputs"] + run["web_outputs"] + run["kb_texts"]
    scored = score_case(
        case, run["answer"], run["suggestion_outputs"], corpus, run["web_outputs"]
    )
    return {
        **case,
        **scored,
        "answer": run["answer"],
        "intent": run["intent"],
        "suggestion_calls": len(run["suggestion_outputs"]),
        "web_calls": len(run["web_outputs"]),
        "error": run["error"] and str(run["error"]),
    }


# Held-out probes written independently of the dataset: new topics (recommendation) and
# distractors that must NOT trigger the suggestions path.
PROBES_RECOMMENDATION = [
    "Alguém indica um bom lugar para fazer manicure em Grenoble?",
    "Qual padaria vocês recomendam para comprar pão de queijo?",
    "Preciso de um eletricista, quem vocês indicam?",
    "Onde posso alugar uma bicicleta boa para passear nos fins de semana?",
    "Indicação de academia de crossfit perto do centro?",
    "Qual livraria tem livros em português?",
]
PROBES_DISTRACTOR = [
    "Oi, tudo bem?",
    "Como faço para renovar meu titre de séjour?",
    "Qual o prazo para pedir a CAF depois de assinar o contrato de aluguel?",
    "Obrigado, ajudou muito!",
    "Como funciona o transporte público TAG em Grenoble?",
    "Quanto custa o timbre fiscal para o titre de séjour?",
]


def run_probes() -> dict[str, Any]:
    out: dict[str, Any] = {"recommendation": [], "distractor": []}
    with ThreadPoolExecutor(4) as ex:
        rec_runs = list(ex.map(run_agent, PROBES_RECOMMENDATION))
        dis_runs = list(ex.map(run_agent, PROBES_DISTRACTOR))
    for q, run in zip(PROBES_RECOMMENDATION, rec_runs):
        corpus = run["suggestion_outputs"] + run["web_outputs"] + run["kb_texts"]
        members = tool_members(run["suggestion_outputs"])
        checks = structural_checks(run["answer"], members)
        waive_web_fallback(checks, parse_items(run["answer"]), run["web_outputs"])
        out["recommendation"].append(
            {
                "question": q,
                "intent": run["intent"],
                "suggestion_calls": len(run["suggestion_outputs"]),
                "web_calls": len(run["web_outputs"]),
                "structural_ok": all(checks.values()),
                "failed_checks": [k for k, v in checks.items() if not v],
                "hallucinations": faithfulness(run["answer"], q, corpus),
                "answer": run["answer"],
            }
        )
    for q, run in zip(PROBES_DISTRACTOR, dis_runs):
        out["distractor"].append(
            {
                "question": q,
                "intent": run["intent"],
                "suggestion_calls": len(run["suggestion_outputs"]),
                "ok": distractor_ok(
                    run["intent"], run["answer"], len(run["suggestion_outputs"])
                ),
                "answer": run["answer"],
            }
        )
    return out


def main() -> None:  # pragma: no cover - needs Qdrant, keys, LLM
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tsv", type=Path, default=DEFAULT_TSV)
    p.add_argument("--split", choices=["tune", "holdout", "all"], default="tune")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument(
        "--probes", action="store_true", help="run probes instead of a split"
    )
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--details", action="store_true")
    args = p.parse_args()

    if args.probes:
        with recording_tools():
            res = run_probes()
        rec, dis = res["recommendation"], res["distractor"]
        print(
            f"recommendation probes: suggestions path {sum(r['suggestion_calls'] > 0 for r in rec)}/{len(rec)}, "
            f"structural ok {sum(r['structural_ok'] for r in rec)}/{len(rec)}, "
            f"hallucinated names {sum(len(r['hallucinations']) for r in rec)}"
        )
        print(
            f"distractors ok (no suggestions path): {sum(r['ok'] for r in dis)}/{len(dis)}"
        )
        for r in rec:
            print(
                " REC",
                r["intent"],
                r["suggestion_calls"],
                r["failed_checks"],
                r["question"],
            )
        for r in dis:
            print(" DIS", r["intent"], r["ok"], r["question"])
        if args.out:
            args.out.write_text(json.dumps(res, ensure_ascii=False, indent=2))
        return

    cases = split_dataset(load_dataset(args.tsv), args.split)
    with recording_tools(), ThreadPoolExecutor(args.workers) as ex:
        rows = list(ex.map(eval_case, cases))
    summary = summarise(rows)
    print(json.dumps({"split": args.split, **summary}, indent=2, ensure_ascii=False))
    if args.details:
        for r in rows:
            failed = [k for k, v in r["checks"].items() if not v]
            print(
                f"{'PASS' if r['passed'] else 'FAIL'} cov={r['coverage']:.2f} "
                f"words={r['words']} intent={r['intent']} failed={failed} "
                f"halluc={r['hallucinations']} | {r['question'][:70]}"
            )
    if args.out:
        args.out.write_text(
            json.dumps(
                {"split": args.split, "summary": summary, "cases": rows},
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
