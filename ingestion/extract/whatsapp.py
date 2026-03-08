from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


# ── Logging ──────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


# ── Config (Local Overrides) ──────────────────────────────────────────────────
@dataclass(frozen=True)
class ParserConfig:
    # WhatsApp export line format:
    # [dd/mm/yy, HH:MM:SS] ~? User: message
    line_pattern: re.Pattern = re.compile(
        r"\[(\d{2}/\d{2}/\d{2}, \d{2}:\d{2}:\d{2})\]\s*~?\s*(.*?):\s(.*)"
    )
    system_patterns: tuple[str, ...] = (
        "joined using",
        "omitted",
        "added",
        "created this group",
        "changed the group",
        "end-to-end encrypted",
        "left",
        "was deleted",
        "you joined",
        "‎",  # hidden control char often present in WhatsApp exports
    )


# ── Parsing ──────────────────────────────────────────────────────────────────
def parse_whatsapp_chat(
    filepath: Path, line_pattern: re.Pattern, timestamp_format: str
) -> pd.DataFrame:
    """
    Parse WhatsApp exported chat into a DataFrame with:
      - timestamp (datetime)
      - user
      - message
      - source_file (filename)
    Handles multi-line messages.
    """
    messages: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None

    if not filepath.exists():
        raise FileNotFoundError(f"WhatsApp chat file not found: {filepath}")

    with filepath.open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            match = line_pattern.match(line)
            if match:
                if current:
                    messages.append(current)
                ts, user, msg = match.groups()
                current = {
                    "timestamp": ts,
                    "user": user.strip(),
                    "message": msg.strip(),
                    "source_file": filepath.name,
                }
            elif current:
                # Continuation of a multi-line message
                continuation = line.strip()
                if continuation:
                    current["message"] += "\n" + continuation

    if current:
        messages.append(current)

    df = pd.DataFrame(messages)
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], format=timestamp_format, errors="coerce"
    )
    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    return df


def remove_system_messages(
    df: pd.DataFrame, system_patterns: tuple[str, ...]
) -> pd.DataFrame:
    """
    Remove WhatsApp system messages (joins/leaves/encryption notices/etc.).
    """
    if df.empty:
        return df

    pattern = "|".join(map(re.escape, system_patterns))
    mask = ~df["message"].str.contains(pattern, na=True, case=False, regex=True)
    return df.loc[mask].reset_index(drop=True)


# ── Classification ───────────────────────────────────────────────────────────
def classify_message(
    msg: str,
    prev_user: Optional[str] = None,
    curr_user: Optional[str] = None,
    prev_is_question: bool = False,
) -> str:
    """
    Classify a message into:
      - question     : seeking information from the group
      - answer       : responding to a preceding question (different user)
      - clarification: follow-up by the same user who asked
      - confirmation : original asker confirms an answer worked
      - noise        : reactions, deleted msgs, kkk, very short acks
      - statement    : everything else (info sharing, announcements)
    """
    if not isinstance(msg, str) or len(msg.strip()) < 3:
        return "noise"

    m = msg.strip()
    ml = m.lower()
    scores = {
        "question": 0,
        "answer": 0,
        "clarification": 0,
        "confirmation": 0,
        "noise": 0,
    }

    # ── NOISE ────────────────────────────────────────────────────────────────
    if re.search(r"(omitted|deleted|This message was)", m):
        scores["noise"] += 10
    if len(m) < 6:
        scores["noise"] += 6
    if re.match(r"^(ok[!.,]?|blz|👍|✅|😂|kkk+|haha+|rsrs+|thx|vlw|👏)$", ml):
        scores["noise"] += 8
    if re.search(r"(kkk{3,}|haha{3,})", ml) and len(m) < 30:
        scores["noise"] += 4

    # ── QUESTION ─────────────────────────────────────────────────────────────
    q_count = m.count("?")
    if q_count == 1:
        scores["question"] += 3
    if q_count >= 2:
        scores["question"] += 6

    if re.search(
        r"algu[eé]m (sabe|j[aá]|aqui|tem|conseguiu|passou|pode|conhece|indica)", ml
    ):
        scores["question"] += 4
    if re.search(r"(voc[eê]s? sabem|voc[eê] sabe)", ml):
        scores["question"] += 3
    if re.search(r"(tenho uma d[úu]vida|uma pergunta|queria (saber|perguntar))", ml):
        scores["question"] += 4
    if re.match(r"^(como |onde |quando |qual |quem |por que |pq |ser[aá] )", ml):
        scores["question"] += 3
    if re.search(r"como (faz|fazer|consigo|posso|funciona)", ml):
        scores["question"] += 2
    if re.search(r"algu[eé]m (recomenda|indica|conhece)", ml):
        scores["question"] += 3
    if (
        re.match(r"^(pessoal[,!]|gente[,!]|oi |ol[aá] |bom dia|boa (tarde|noite))", ml)
        and "?" in m
    ):
        scores["question"] += 2
    if re.search(r"(como voc[eê] (t[aá]|est[aá])|tudo bem)", ml):
        scores["question"] -= 2  # social chat

    # ── ANSWER ───────────────────────────────────────────────────────────────
    if prev_is_question and (curr_user is not None) and (curr_user != prev_user):
        scores["answer"] += 3  # replying to question from different user

    if (
        re.match(r"^(sim[,!. ]|n[aã]o[,!. ]|[eé] isso|exato|correto|claro[,!])", ml)
        and "?" not in m
    ):
        scores["answer"] += 4
    if (
        re.search(r"(voc[eê] precisa|tem que |deve |[eé] s[oó] |basta )", ml)
        and "?" not in m
    ):
        scores["answer"] += 3
    if (
        re.search(r"(eu fiz|eu fui|no meu caso|comigo foi|passei por isso)", ml)
        and "?" not in m
    ):
        scores["answer"] += 3
    if re.search(r"(https?://|www\.)", ml) and "?" not in m:
        scores["answer"] += 2
    if (
        re.search(r"(o processo [eé]|funciona assim|o que acontece)", ml)
        and "?" not in m
    ):
        scores["answer"] += 3
    if (
        re.search(r"([eé] na|fica na|voc[eê] vai|vai precisar|precisa levar)", ml)
        and "?" not in m
    ):
        scores["answer"] += 2
    if "?" in m:
        scores["answer"] -= 3  # still asking = not a clean answer

    # ── CLARIFICATION ────────────────────────────────────────────────────────
    if (curr_user == prev_user) and ("?" in m):
        scores["clarification"] += 4
    if re.search(r"(tipo assim|ou seja|quero dizer|me refiro)", ml):
        scores["clarification"] += 2

    # ── CONFIRMATION ─────────────────────────────────────────────────────────
    if (
        re.search(
            r"\b(funcionou|deu certo|resolveu|obrigad[ao]|muito obrigad|valeu)\b", ml
        )
        and len(m) < 100
    ):
        scores["confirmation"] += 4
    if re.match(
        r"^([oó]timo|perfeito|top[,!]|show[,!]|massa[,!]|entendi[,!]|consegui)", ml
    ):
        scores["confirmation"] += 3

    # ── DECISION ─────────────────────────────────────────────────────────────
    best = max(scores, key=scores.get)
    if scores[best] < 2:
        return "statement"
    if best == "answer" and scores["answer"] < 3:
        return "statement"
    return best


def classify_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add msg_type column using sequential context (previous user / previous question).
    """
    if df.empty:
        df["msg_type"] = []
        return df

    df = df.copy()
    types: List[str] = []
    prev_user: Optional[str] = None
    prev_is_q = False

    for _, row in df.iterrows():
        label = classify_message(
            row["message"],
            prev_user=prev_user,
            curr_user=row["user"],
            prev_is_question=prev_is_q,
        )
        types.append(label)
        prev_user = row["user"]
        prev_is_q = label == "question"

    df["msg_type"] = types
    return df


# ── Orchestrator ─────────────────────────────────────────────────────────────
def run_parser(chat_path: Path, output_dir: Path, timestamp_format: str) -> Path:
    cfg = ParserConfig()

    logger.info("Reading chat file: %s", chat_path)
    df = parse_whatsapp_chat(chat_path, cfg.line_pattern, timestamp_format)

    logger.info("Parsed %s messages", f"{len(df):,}")
    df = remove_system_messages(df, cfg.system_patterns)
    logger.info("After removing system messages: %s", f"{len(df):,}")

    df = classify_all(df)
    logger.info(
        "Message type counts:\n%s",
        df["msg_type"].value_counts(dropna=False).to_string(),
    )

    # Standardized output name: classified.csv
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "classified.csv"

    df.to_csv(out_path, index=False)
    logger.info("Saved: %s", out_path)
    return out_path
