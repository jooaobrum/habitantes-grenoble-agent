"""Opt-out list: business names that must never become Suggestions.

One name per line in `config/suggestion_exclusions.txt` (`#` comments and blank
lines ignored), matched with `normalise_name` so spelling variants are covered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Set

from ingestion.suggestions.extract import Mention
from ingestion.suggestions.merge import normalise_name
from ingestion.suggestions.suggestions import Suggestion

DEFAULT_EXCLUSIONS_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "suggestion_exclusions.txt"
)


def load_exclusions(path: Path | None = None) -> Set[str]:
    """Normalised excluded names; a missing file excludes nothing."""
    path = path or DEFAULT_EXCLUSIONS_PATH
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key = normalise_name(line)
            if key:
                names.add(key)
    return names


def exclude_mentions(mentions: Iterable[Mention], excluded: Set[str]) -> List[Mention]:
    return [m for m in mentions if normalise_name(m.name) not in excluded]


def exclude_suggestions(
    suggestions: Iterable[Suggestion], excluded: Set[str]
) -> List[Suggestion]:
    return [s for s in suggestions if normalise_name(s.name) not in excluded]
