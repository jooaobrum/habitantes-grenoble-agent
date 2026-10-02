"""Name normalisation (code) and per-Kind variant merge (one LLM pass).

Counting must happen only after this step: "Gran Free" and "Grand Frais" are one
Suggestion, and a chain is one Suggestion whichever branch is named.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Dict, List

import httpx

from habitantes.domain.suggestions import Kind
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.llm import chat_json

logger = logging.getLogger(__name__)

_GENERIC = {"le", "la", "les", "l", "du", "de", "des", "da", "do", "o", "a", "the"}


def normalise_name(name: str) -> str:
    """Case, accents, punctuation and generic words removed."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    kept = [w for w in words if w not in _GENERIC]
    return " ".join(kept or words)


# Entities that are never Suggestions (banks, phone operators, apps, public
# services...). Matched on the normalised name (whole name or leading words).
EXCLUDED_NAMES = frozenset(
    normalise_name(n)
    for n in (
        "BNP Paribas",
        "Crédit Agricole",
        "Société Générale",
        "Caisse d'Epargne",
        "LCL",
        "Crédit Mutuel",
        "La Banque Postale",
        "Boursorama",
        "Revolut",
        "N26",
        "SFR",
        "Bouygues Telecom",
        "Free Mobile",
        "Lebara",
        "Sosh",
        "WhatsApp",
        "Uber",
        "Doctolib",
        "Airbnb",
        "Instagram",
        "CAF",
        "CPAM",
        "Pôle Emploi",
        "France Travail",
        "Préfecture",
        "Mairie",
        "Ameli",
        "Impots",
    )
)


def is_excluded(name: str) -> bool:
    key = normalise_name(name)
    return any(key == e or key.startswith(e + " ") for e in EXCLUDED_NAMES)


MERGE_PROMPT = """Abaixo estão nomes de negócios do tipo "{kind}" citados num grupo de WhatsApp (podem ter erros de grafia, acentos diferentes ou ser filiais de uma mesma rede).
Agrupe os nomes que se referem ao MESMO negócio; filiais de uma rede são o mesmo negócio (use o nome da rede). Escolha um nome canônico por grupo. Só inclua grupos com 2 ou mais variantes.
Responda em JSON: {{"groups": [{{"canonical": "...", "variants": ["...", "..."]}}]}}.

Nomes:
{names}
"""


async def merge_variants(
    mentions: List[Mention],
    cfg: Any,
    client: httpx.AsyncClient,
) -> List[Mention]:
    """Return Mentions renamed to their canonical name (same order, same fields)."""
    mentions = [m for m in mentions if not is_excluded(m.name)]
    by_kind: Dict[Kind, List[Mention]] = defaultdict(list)
    for m in mentions:
        by_kind[m.kind].append(m)

    canonical: Dict[tuple, str] = {}  # (kind, normalised) -> display name
    for kind, ms in by_kind.items():
        display: Dict[str, Counter] = defaultdict(Counter)
        for m in ms:
            display[normalise_name(m.name)][m.name.strip()] += 1
        to_canon = {k: c.most_common(1)[0][0] for k, c in display.items()}
        if len(display) > 1:
            names = "\n".join(f"- {n}" for n in sorted(to_canon.values()))
            out = await chat_json(
                client, MERGE_PROMPT.format(kind=kind.value, names=names), cfg
            )
            if out is None:
                logger.warning("Variant merge failed for %s; normalised only", kind)
            for g in (out or {}).get("groups", []):
                try:
                    target = str(g["canonical"]).strip()
                    variants = [str(v) for v in g["variants"]] + [target]
                except (KeyError, TypeError):
                    continue
                for v in variants:
                    vkey = normalise_name(v)
                    if vkey in to_canon and target:
                        to_canon[vkey] = target
        for k, shown in to_canon.items():
            canonical[(kind, k)] = shown

    out_mentions = []
    for m in mentions:
        key = normalise_name(m.name)
        shown = canonical[(m.kind, key)]
        out_mentions.append(m.model_copy(update={"name": shown}))
    return out_mentions
