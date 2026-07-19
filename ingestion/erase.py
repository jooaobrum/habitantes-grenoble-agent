from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

import pandas as pd

# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

REDACTED_MESSAGE = "[mensagem removida a pedido do usuário]"

# Same header shape as ingestion/extract/whatsapp.py's ParserConfig.line_pattern,
# but captures the raw prefix/user/separator so a redacted line can be rebuilt
# without disturbing the file's structure (timestamps, thread order).
RAW_LINE_PATTERN = re.compile(
    r"^(\[\d{2}/\d{2}/\d{2}, \d{2}:\d{2}:\d{2}\]\s*~?\s*)(.*?)(:\s)(.*)$"
)

Matcher = Callable[[str], bool]


# ── Identifier matching ─────────────────────────────────────────────────────
def _normalize(value: str) -> str:
    return re.sub(r"[\s\-()]", "", value).strip().lower()


def build_matcher(identifiers: Iterable[str]) -> Matcher:
    """Build a matcher for names/phone numbers as they appear in WhatsApp
    exports (e.g. "Fulano de Tal" or "+33 6 12 34 56 78"). Matching is exact
    after normalizing whitespace/punctuation/case, on purpose — a substring
    match risks erasing the wrong person's messages."""
    normalized = {_normalize(i) for i in identifiers if i and i.strip()}
    if not normalized:
        raise ValueError("At least one non-empty identifier is required.")

    def matches(user: str) -> bool:
        return bool(user) and _normalize(user) in normalized

    return matches


def _record_matches(rec: Dict[str, Any], matches: Matcher) -> bool:
    q_user = rec.get("question_user") or rec.get("user")
    if q_user and matches(str(q_user)):
        return True
    for u in rec.get("answer_users") or []:
        if matches(str(u)):
            return True
    ctx = rec.get("context")
    if isinstance(ctx, list):
        for c in ctx:
            if isinstance(c, dict) and matches(str(c.get("user", ""))):
                return True
    return False


# ── Raw export (.txt) ────────────────────────────────────────────────────────
def redact_raw_export(filepath: Path, matches: Matcher, dry_run: bool = True) -> int:
    """Blank out the message text (and its continuation lines) for matched
    users in a raw WhatsApp .txt export. Keeps the header line (timestamp +
    user) so thread structure/order is preserved for everyone else."""
    if not filepath.exists():
        return 0

    raw_lines = filepath.read_text(encoding="utf-8").splitlines(keepends=True)
    out_lines: List[str] = []
    redacting_continuation = False
    n_redacted = 0

    for raw_line in raw_lines:
        line = raw_line.rstrip("\n")
        m = RAW_LINE_PATTERN.match(line)
        if m:
            prefix, user, sep, _msg = m.groups()
            if matches(user.strip()):
                out_lines.append(f"{prefix}{user}{sep}{REDACTED_MESSAGE}\n")
                redacting_continuation = True
                n_redacted += 1
            else:
                out_lines.append(raw_line)
                redacting_continuation = False
        else:
            if redacting_continuation and line.strip():
                continue  # drop continuation line belonging to a redacted message
            out_lines.append(raw_line)

    if n_redacted and not dry_run:
        filepath.write_text("".join(out_lines), encoding="utf-8")

    return n_redacted


# ── Intermediate CSV artifacts (classified.csv, qa_pairs*.csv) ──────────────
def purge_csv(filepath: Path, matches: Matcher, dry_run: bool = True) -> int:
    if not filepath.exists():
        return 0

    df = pd.read_csv(filepath)
    if df.empty:
        return 0

    def row_matches(row: pd.Series) -> bool:
        for col in ("user", "question_user"):
            val = row.get(col)
            if isinstance(val, str) and matches(val):
                return True
        answer_users = row.get("answer_users")
        if isinstance(answer_users, str):
            for candidate in re.findall(r"['\"]([^'\"]+)['\"]", answer_users):
                if matches(candidate):
                    return True
        return False

    mask = df.apply(row_matches, axis=1)
    n_removed = int(mask.sum())

    if n_removed and not dry_run:
        df.loc[~mask].to_csv(filepath, index=False)

    return n_removed


# ── Intermediate JSON/JSONL artifacts (qa_pairs*.json, synthesis_results.jsonl) ──
def purge_json_records(filepath: Path, matches: Matcher, dry_run: bool = True) -> int:
    if not filepath.exists():
        return 0

    data = json.loads(filepath.read_text(encoding="utf-8") or "[]")
    kept = [rec for rec in data if not _record_matches(rec, matches)]
    n_removed = len(data) - len(kept)

    if n_removed and not dry_run:
        filepath.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return n_removed


def purge_jsonl_records(filepath: Path, matches: Matcher, dry_run: bool = True) -> int:
    if not filepath.exists():
        return 0

    lines = [
        json.loads(line)
        for line in filepath.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kept = [rec for rec in lines if not _record_matches(rec, matches)]
    n_removed = len(lines) - len(kept)

    if n_removed and not dry_run:
        with filepath.open("w", encoding="utf-8") as f:
            for rec in kept:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return n_removed


# ── Live bot logs (interactions.jsonl / feedback.jsonl) ──────────────────────
def purge_logs_by_chat_id(
    filepath: Path, chat_ids: Iterable[str], dry_run: bool = True
) -> int:
    """chat_id in these logs is already a salted hash (see
    app/whatsapp_bot/src/guards.ts), so this is a plain line filter — no
    identity reversal needed, the caller supplies the exact hash(es)."""
    if not filepath.exists():
        return 0

    targets = {c for c in chat_ids if c}
    if not targets:
        return 0

    lines = [
        json.loads(line)
        for line in filepath.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kept = [rec for rec in lines if str(rec.get("chat_id")) not in targets]
    n_removed = len(lines) - len(kept)

    if n_removed and not dry_run:
        with filepath.open("w", encoding="utf-8") as f:
            for rec in kept:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return n_removed


# ── Qdrant (production knowledge base) ───────────────────────────────────────
def qdrant_point_ids_for_matches(synthesis_path: Path, matches: Matcher) -> List[str]:
    """Records erased from synthesis_results.jsonl still carry question_user /
    answer_users (stripped only at the final make_payload() whitelist step),
    so we can compute the same stable_point_id used at load time and delete
    those exact points from the live collection."""
    if not synthesis_path.exists():
        return []

    from ingestion.load.qdrant import stable_point_id

    ids: List[str] = []
    for line in synthesis_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if _record_matches(rec, matches):
            ids.append(stable_point_id(rec))
    return ids


def delete_from_qdrant(
    collection_name: str, point_ids: List[str], dry_run: bool = True
) -> int:
    if not point_ids:
        return 0
    if dry_run:
        return len(point_ids)

    import os

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels

    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    qclient = QdrantClient(url=qdrant_url, api_key=os.getenv("QDRANT_API_KEY"))
    qclient.delete(
        collection_name=collection_name,
        points_selector=qmodels.PointIdsList(points=point_ids),
    )
    return len(point_ids)


# ── Orchestrator ─────────────────────────────────────────────────────────────
def erase_user_data(
    identifiers: List[str],
    data_dir: Path,
    artifacts_dir: Path,
    collection_name: str,
    dry_run: bool = True,
) -> Dict[str, int]:
    """Right-to-erasure sweep: redacts a person's messages from the raw
    WhatsApp export, removes their records from every intermediate ingestion
    artifact, and deletes the matching points from the live Qdrant knowledge
    base (identified before the anonymizing payload whitelist strips the
    identifying fields)."""
    matches = build_matcher(identifiers)
    report = {
        "raw_lines_redacted": 0,
        "csv_rows_removed": 0,
        "json_records_removed": 0,
        "qdrant_points_removed": 0,
    }

    for txt_file in sorted(data_dir.glob("*.txt")):
        report["raw_lines_redacted"] += redact_raw_export(
            txt_file, matches, dry_run=dry_run
        )

    for csv_file in sorted(artifacts_dir.rglob("classified.csv")):
        report["csv_rows_removed"] += purge_csv(csv_file, matches, dry_run=dry_run)
    for csv_file in sorted(artifacts_dir.rglob("qa_pairs*.csv")):
        report["csv_rows_removed"] += purge_csv(csv_file, matches, dry_run=dry_run)

    for json_file in sorted(artifacts_dir.rglob("qa_pairs*.json")):
        report["json_records_removed"] += purge_json_records(
            json_file, matches, dry_run=dry_run
        )

    for jsonl_file in sorted(artifacts_dir.rglob("synthesis_results.jsonl")):
        point_ids = qdrant_point_ids_for_matches(jsonl_file, matches)
        report["qdrant_points_removed"] += delete_from_qdrant(
            collection_name, point_ids, dry_run=dry_run
        )
        report["json_records_removed"] += purge_jsonl_records(
            jsonl_file, matches, dry_run=dry_run
        )

    concat_dir = artifacts_dir / "concat"
    if concat_dir.exists():
        for jsonl_file in sorted(concat_dir.glob("*.jsonl")):
            report["json_records_removed"] += purge_jsonl_records(
                jsonl_file, matches, dry_run=dry_run
            )

    return report


# ── CLI ───────────────────────────────────────────────────────────────────────
def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    from dotenv import load_dotenv

    from ingestion.config import settings

    root_dir = Path(__file__).parents[1]
    load_dotenv(root_dir / ".env")

    parser = argparse.ArgumentParser(
        description=(
            "Erase a person's messages from the ingestion pipeline: raw "
            "WhatsApp export, intermediate artifacts, and the live Qdrant "
            "knowledge base. Runs in dry-run mode by default."
        )
    )
    parser.add_argument(
        "--identifier",
        action="append",
        required=True,
        help=(
            "Name or phone number exactly as it appears in the WhatsApp "
            "export (repeatable, e.g. --identifier 'Fulano' --identifier "
            "'+33 6 12 34 56 78')."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Without this flag, only reports counts.",
    )
    args = parser.parse_args()

    report = erase_user_data(
        identifiers=args.identifier,
        data_dir=root_dir / settings.data_dir,
        artifacts_dir=root_dir / settings.artifacts_dir,
        collection_name=settings.load.collection_name,
        dry_run=not args.apply,
    )

    mode = (
        "APLICADO" if args.apply else "SIMULAÇÃO (use --apply para gravar as remoções)"
    )
    logger.info("Modo: %s", mode)
    for key, value in report.items():
        logger.info("%s: %d", key, value)

    if not args.apply and sum(report.values()) > 0:
        logger.info("Nenhum arquivo foi alterado. Rode novamente com --apply.")


if __name__ == "__main__":
    sys.exit(main())
