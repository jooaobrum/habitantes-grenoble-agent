"""Author-free check for derived Suggestion data (Mentions, Suggestions, payloads)."""

from __future__ import annotations

import re
from typing import Iterable, List

from ingestion.suggestions.extract import _PHONE_RE

_MEMBER_TAG_RE = re.compile(r"\bM\d+\b")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")  # stored dates are not phone numbers


def find_pii_leaks(text: str, author_names: Iterable[str]) -> List[str]:
    """Author names, member tags (M1, M2...) and phone numbers found in `text`."""
    leaks: List[str] = []
    for name in author_names:
        if name.strip() and re.search(re.escape(name.strip()), text, re.IGNORECASE):
            leaks.append(f"author:{name}")
    leaks += [f"tag:{t}" for t in _MEMBER_TAG_RE.findall(text)]
    leaks += [
        f"phone:{p.strip()}" for p in _PHONE_RE.findall(_ISO_DATE_RE.sub(" ", text))
    ]
    return leaks
