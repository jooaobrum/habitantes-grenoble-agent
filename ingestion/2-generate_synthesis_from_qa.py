from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
import pandas as pd

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


# ── Config ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class BatchConfig:
    input_dir: Path
    output_dir: Path
    prompt_path: Path
    model: str
    temperature: float
    max_retries: int
    retry_base_sleep_s: float
    only_inputs_matching: str
    overwrite: bool
    skip_bad_questions: bool = True
    start_time: Optional[str] = None
    end_time: Optional[str] = None


# ── Utilities ────────────────────────────────────────────────────────────────
def load_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


def safe_slug(s: str, max_len: int = 140) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-_.]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-_.")
    return s[:max_len] if s else "na"


def normalize_source_file(source_file: Any) -> str:
    """
    Expect: 'chat-19012021-20022026.txt' (or full path)
    Return: 'chat-19012021-20022026'
    """
    if not source_file:
        return "unknown_source"
    s = str(source_file).strip()
    s = Path(s).name
    stem = Path(s).stem
    return stem if stem else "unknown_source"


def normalize_thread_id(thread_id: Any) -> str:
    """
    Convert thread_id to safe string. Prefer int-like.
    """
    if thread_id is None or str(thread_id).strip() == "":
        return "na"
    try:
        return str(int(thread_id))
    except Exception:
        return safe_slug(str(thread_id).strip(), max_len=60) or "na"


def normalize_question_time(qt: Any) -> str:
    """
    Expect: '2021-01-29 15:44:19'
    Return: '20210129T154419'
    """
    if not qt:
        return "na"
    s = str(qt).strip()
    s = s[:19]
    s = s.replace("-", "").replace(":", "").replace(" ", "T")
    return safe_slug(s, max_len=40) or "na"


def record_fingerprint(rec: Dict[str, Any]) -> str:
    """
    Stable short hash so filenames never collide even if timestamps are missing/duplicated.
    """
    payload = f'{rec.get("question_time","")}|{rec.get("question","")}|{rec.get("thread_start","")}'
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:8]


def iter_input_files(cfg: BatchConfig) -> List[Path]:
    pattern = re.compile(cfg.only_inputs_matching)
    files = sorted([p for p in cfg.input_dir.glob("*.json") if pattern.match(p.name)])
    if not files:
        raise FileNotFoundError(
            f"No JSON files matched in {cfg.input_dir} with pattern {cfg.only_inputs_matching}"
        )
    return files


def load_records(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        return [data]

    if not isinstance(data, list):
        raise ValueError(
            f"{path.name} must be a JSON list of records (or a single dict)."
        )

    bad = [i for i, x in enumerate(data) if not isinstance(x, dict)]
    if bad:
        raise ValueError(f"{path.name} has non-dict records at positions: {bad[:10]}")

    return data


def build_output_path(cfg: BatchConfig, rec: Dict[str, Any]) -> Path:
    """
    Filename rule (requested):
      source_file - thread_id

    But because multiple QAs can exist per thread_id, we add question_time + short hash.
    Example:
      chat-19012021-20022026__thread-17__t-20210129T154419__a1b2c3d4.json
    """
    source = normalize_source_file(rec.get("source_file"))
    tid = normalize_thread_id(rec.get("thread_id"))
    qt = normalize_question_time(rec.get("question_time"))
    fp = record_fingerprint(rec)

    filename = f"{source}__thread-{tid}__t-{qt}__{fp}.json"
    return cfg.output_dir / filename


# ── Optional filter: skip "fake questions" (thanks/ack) ───────────────────────
CONFIRMATION_LIKE = re.compile(
    r"\b(valeu|obrigad[ao]|obg|show|top|perfeito|massa|funcionou|deu certo|era isso|entendi)\b",
    re.IGNORECASE,
)


def is_bad_question(rec: Dict[str, Any]) -> bool:
    q = str(rec.get("question", "")).strip()
    if len(q) < 6:
        return True
    ql = q.lower()
    # no "?" and looks like confirmation/ack
    if "?" not in q and CONFIRMATION_LIKE.search(ql):
        return True
    return False


# ── OpenAI call ──────────────────────────────────────────────────────────────
def call_openai(
    client: OpenAI,
    cfg: BatchConfig,
    prompt_template: str,
    qa_record: Dict[str, Any],
) -> Dict[str, Any]:
    prompt = prompt_template.format(
        qa_record_json=json.dumps(qa_record, ensure_ascii=False)
    )

    last_err: Optional[Exception] = None

    for attempt in range(cfg.max_retries):
        try:
            response = client.responses.create(
                model=cfg.model,
                input=prompt,
                temperature=cfg.temperature,
            )
            output_text = response.output_text.strip()
            return json.loads(output_text)

        except Exception as e:
            last_err = e
            sleep_time = cfg.retry_base_sleep_s * (2**attempt)
            logger.warning(
                "OpenAI error (attempt %s/%s): %s — sleeping %.1fs",
                attempt + 1,
                cfg.max_retries,
                repr(e),
                sleep_time,
            )
            time.sleep(sleep_time)

    raise RuntimeError(f"Failed after retries: {repr(last_err)}")


# ── Main batch runner ─────────────────────────────────────────────────────────
def run_batch(cfg: BatchConfig) -> None:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not found (set it in .env or environment)."
        )

    # --- NEW: date range filter helpers (thread_start) ------------------------
    # Expect cfg.start_time / cfg.end_time as strings like "2021-01-01 00:00:00"
    # or ISO "2021-01-01T00:00:00". Either can be None.
    start_dt = (
        pd.to_datetime(cfg.start_time) if getattr(cfg, "start_time", None) else None
    )
    end_dt = pd.to_datetime(cfg.end_time) if getattr(cfg, "end_time", None) else None

    def in_range_thread_start(rec: dict) -> bool:
        ts = rec.get("thread_start")
        if not ts:
            return False  # drop if missing (safer)
        try:
            ts_dt = pd.to_datetime(ts)
        except Exception:
            return False
        if start_dt is not None and ts_dt < start_dt:
            return False
        if end_dt is not None and ts_dt > end_dt:
            return False
        return True

    # ------------------------------------------------------------------------

    client = OpenAI(api_key=api_key)
    prompt_template = load_prompt(cfg.prompt_path)

    input_files = iter_input_files(cfg)
    logger.info("Found %d input file(s)", len(input_files))

    total_in = 0
    total_out = 0
    skipped = 0
    filtered = 0
    filtered_date = 0  # NEW

    for input_file in input_files:
        records = load_records(input_file)
        logger.info("Processing %s (%d records)", input_file.name, len(records))
        total_in += len(records)

        for rec in records:
            # --- NEW: filter by thread_start date range -----------------------
            if not in_range_thread_start(rec):
                filtered_date += 1
                continue
            # -----------------------------------------------------------------

            if cfg.skip_bad_questions and is_bad_question(rec):
                filtered += 1
                continue

            out_path = build_output_path(cfg, rec)

            if out_path.exists() and not cfg.overwrite:
                skipped += 1
                continue

            kb_entry = call_openai(client, cfg, prompt_template, rec)

            # Traceability
            kb_entry["_trace"] = {
                "input_file": input_file.name,
                "source_file": rec.get("source_file"),
                "thread_id": rec.get("thread_id"),
                "thread_start": rec.get("thread_start"),  # NEW (useful)
                "question_time": rec.get("question_time"),
                "score": rec.get("score"),
                "tier": rec.get("tier"),
            }

            out_path.write_text(
                json.dumps(kb_entry, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            total_out += 1

        logger.info("Finished %s", input_file.name)

    logger.info("Batch complete.")
    logger.info("  input records             : %s", f"{total_in:,}")
    logger.info("  outputs written           : %s", f"{total_out:,}")
    logger.info("  skipped (exists)          : %s", f"{skipped:,}")
    logger.info("  filtered (bad Q)          : %s", f"{filtered:,}")
    logger.info("  filtered (thread_start dt): %s", f"{filtered_date:,}")  # NEW
    logger.info("  output folder             : %s", cfg.output_dir)


# ── Entry point: choose variables here ────────────────────────────────────────
if __name__ == "__main__":
    # ✅ Set these to what you want (all config lives in main, as requested)
    INPUT_DIR = Path("../artifacts/chat-19012021-20022026/0-kb_raw/test")
    OUTPUT_DIR = Path("../artifacts/chat-19012021-20022026/1-kb_threads_medium")
    PROMPT_PATH = Path("../prompts/synthesis_prompt.txt")
    START_TIME = "2024-02-15T00:00:00"
    END_TIME = "2027-12-31T23:59:59"

    # You can set OPENAI_MODEL in .env, but override here if you want
    load_dotenv()
    MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    config = BatchConfig(
        input_dir=INPUT_DIR,
        output_dir=OUTPUT_DIR,
        prompt_path=PROMPT_PATH,
        model=MODEL,
        temperature=0.2,
        max_retries=4,
        retry_base_sleep_s=1.5,
        # Picks: chat-xxxx-qa_pairs.json, chat-xxxx-qa_pairs-high.json, etc.
        only_inputs_matching=r".*-qa_pairs.*\.json$",
        overwrite=False,
        skip_bad_questions=True,  # skips "valeu / obrigado" style non-questions
        start_time=START_TIME,
        end_time=END_TIME,
    )

    run_batch(config)
