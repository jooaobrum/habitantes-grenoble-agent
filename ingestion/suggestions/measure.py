"""Score Mention extraction against hand-labelled Threads.

Input: the JSONL written by `labelling.py`, with `suggestions` filled in by the
maintainer. Each label: {"name", "kind", "polarity", "evidence": [message idx]}.

Reports, per Kind:
  - window coverage: labelled Suggestions whose evidence messages all sit inside
    one candidate window (the rest are invisible to extraction);
  - extraction recall: labelled Suggestions matched by an extracted Mention
    (same Kind, names equal or one contained in the other, accents/case ignored);
  - wrong extractions: extracted Mentions matching no label.

The extraction run is injectable (`Extractor`) so the scoring is testable with a
fake; the default runs the real Jev filter + LLM extraction.

Run with `make labelling-measure`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Sequence

from habitantes.domain.suggestions import Kind
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.windows import Window, thread_windows

# window -> Mentions extracted from it (Jev filter included when real).
Extractor = Callable[[Window], Awaitable[List[Mention]]]


@dataclass
class KindStats:
    labelled: int = 0
    covered: int = 0
    recalled: int = 0
    extracted: int = 0
    wrong: int = 0


@dataclass
class Report:
    per_kind: Dict[str, KindStats] = field(default_factory=dict)
    uncovered: List[Dict[str, Any]] = field(default_factory=list)
    missed: List[Dict[str, Any]] = field(default_factory=list)
    wrong_mentions: List[Dict[str, Any]] = field(default_factory=list)

    def total(self) -> KindStats:
        t = KindStats()
        for s in self.per_kind.values():
            for f in ("labelled", "covered", "recalled", "extracted", "wrong"):
                setattr(t, f, getattr(t, f) + getattr(s, f))
        return t


def normalise(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def names_match(a: str, b: str) -> bool:
    a, b = normalise(a), normalise(b)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def load_labelled(path: Path) -> List[Dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _validate(label: Dict[str, Any], thread_id: Any, n_msgs: int) -> None:
    kind = label.get("kind")
    if kind not in {k.value for k in Kind}:
        raise ValueError(f"thread {thread_id}: unknown kind {kind!r}")
    if not label.get("name"):
        raise ValueError(f"thread {thread_id}: label without name")
    ev = label.get("evidence")
    if not ev or any(not isinstance(i, int) or not 0 <= i < n_msgs for i in ev):
        raise ValueError(
            f"thread {thread_id}: label {label.get('name')!r} needs `evidence` "
            f"message indices in 0..{n_msgs - 1}"
        )


async def measure(
    threads: Sequence[Dict[str, Any]],
    extractor: Extractor,
    before: int,
    after_request: int,
    after_other: int,
) -> Report:
    report = Report()

    def stats(kind: str) -> KindStats:
        return report.per_kind.setdefault(kind, KindStats())

    for th in threads:
        tid = th["thread_id"]
        msgs = th["messages"]
        labels = th.get("suggestions", [])
        for lb in labels:
            _validate(lb, tid, len(msgs))
        spans = thread_windows(msgs, before, after_request, after_other)

        for lb in labels:
            stats(lb["kind"]).labelled += 1
            ev = lb["evidence"]
            if any(s <= min(ev) and max(ev) <= e for s, e in spans):
                stats(lb["kind"]).covered += 1
            else:
                report.uncovered.append({"thread_id": tid, **lb})

        extracted: List[Mention] = []
        for s, e in spans:
            extracted.extend(await extractor(Window(tid, msgs[s : e + 1])))

        matched_labels: set[int] = set()
        for m in extracted:
            stats(m.kind.value).extracted += 1
            hit = next(
                (
                    i
                    for i, lb in enumerate(labels)
                    if lb["kind"] == m.kind.value and names_match(lb["name"], m.name)
                ),
                None,
            )
            if hit is None:
                stats(m.kind.value).wrong += 1
                report.wrong_mentions.append(
                    {"thread_id": tid, "name": m.name, "kind": m.kind.value}
                )
            else:
                matched_labels.add(hit)
        for i, lb in enumerate(labels):
            if i in matched_labels:
                stats(lb["kind"]).recalled += 1
            else:
                report.missed.append({"thread_id": tid, **lb})
    return report


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:.0f}%" if den else "n/a"


def format_report(report: Report) -> str:
    rows = [
        "kind | labelled | window coverage | recall | extracted | wrong",
        "-----|----------|-----------------|--------|-----------|------",
    ]
    for kind, s in sorted(report.per_kind.items()):
        rows.append(_row(kind, s))
    rows.append(_row("TOTAL", report.total()))
    t = report.total()
    rows.append("")
    rows.append(
        f"Outside every window: {t.labelled - t.covered} of {t.labelled} "
        f"labelled Suggestions ({_pct(t.labelled - t.covered, t.labelled)})."
    )
    return "\n".join(rows)


def _row(kind: str, s: KindStats) -> str:
    return (
        f"{kind} | {s.labelled} | {s.covered} ({_pct(s.covered, s.labelled)}) | "
        f"{s.recalled} ({_pct(s.recalled, s.labelled)}) | {s.extracted} | "
        f"{s.wrong} ({_pct(s.wrong, s.extracted)})"
    )


def make_real_extractor() -> Extractor:  # pragma: no cover - needs network
    """Jev yes/no filter then LLM extraction, using the configured models."""
    import httpx

    from ingestion.config import settings
    from ingestion.preprocess.jev import classify_window
    from ingestion.suggestions.extract import extract_mentions, pseudonymise

    jev, sug, ext = settings.jev, settings.suggestions, settings.mention_extraction
    client = httpx.AsyncClient()

    async def run(window: Window) -> List[Mention]:
        text, _ = pseudonymise(window)
        verdict = await classify_window(
            client,
            text,
            model=jev.model,
            base_url=jev.base_url,
            cutoff=sug.jev_cutoff,
            max_retries=jev.max_retries,
            retry_base_sleep_s=jev.retry_base_sleep_s,
        )
        if not verdict:
            return []
        found = await extract_mentions(
            client,
            window,
            model=ext.model,
            base_url=ext.base_url,
            temperature=ext.temperature,
            max_retries=ext.max_retries,
            retry_base_sleep_s=ext.retry_base_sleep_s,
        )
        return found or []

    return run


def main() -> None:  # pragma: no cover - CLI glue
    from dotenv import load_dotenv

    from ingestion.config import settings

    root = Path(__file__).parents[2]
    load_dotenv(root / ".env")
    default = (
        root
        / settings.artifacts_dir
        / Path(settings.input_file).stem
        / "labelling_sample.jsonl"
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--labelled", type=Path, default=default)
    p.add_argument("--before", type=int, default=settings.suggestions.window_before)
    p.add_argument(
        "--after-request", type=int, default=settings.suggestions.window_after_request
    )
    p.add_argument(
        "--after-other", type=int, default=settings.suggestions.window_after_other
    )
    p.add_argument("--details", action="store_true", help="list uncovered/missed/wrong")
    args = p.parse_args()

    threads = load_labelled(args.labelled)
    if not any(t.get("suggestions") for t in threads):
        raise SystemExit(f"No labels found in {args.labelled}: label it first.")
    report = asyncio.run(
        measure(
            threads,
            make_real_extractor(),
            args.before,
            args.after_request,
            args.after_other,
        )
    )
    print(format_report(report))
    if args.details:
        for title, items in (
            ("Outside windows", report.uncovered),
            ("Missed", report.missed),
            ("Wrong", report.wrong_mentions),
        ):
            print(f"\n{title}:")
            for it in items:
                print("  ", json.dumps(it, ensure_ascii=False))


if __name__ == "__main__":
    main()
