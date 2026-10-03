"""Suggestions: Mentions consolidated per (normalised name, Kind).

`suggestions.jsonl` is the author-free source for every rebuild: each line is a
Suggestion carrying its (author-free) Mentions, so ranking and clustering can be
re-run from disk without the chat export.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

from pydantic import BaseModel, ConfigDict

from habitantes.domain.suggestions import Kind, Topic, topic_for_kind
from ingestion.suggestions.extract import Mention
from ingestion.suggestions.merge import normalise_name

SUGGESTIONS_FILENAME = "suggestions.jsonl"


class Suggestion(BaseModel):
    """One business/place/product. Deliberately has no author field.

    Counts only include Mentions that count: an advertiser's own post
    (`community_business` Mention) is stored but never counted.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Kind
    topic: Topic
    thumbs_up: int = 0
    thumbs_down: int = 0
    last_date: date
    items: List[str] = []
    contexts: List[str] = []
    community_business: bool = False
    mentions: List[Mention] = []

    @property
    def counted(self) -> List[Mention]:
        return [m for m in self.mentions if not m.community_business]


def aggregate(mentions: List[Mention]) -> List[Suggestion]:
    """Group canonical-name Mentions by (normalised name, Kind)."""
    groups: Dict[Tuple[Kind, str], List[Mention]] = {}
    for m in mentions:
        groups.setdefault((m.kind, normalise_name(m.name)), []).append(m)
    out: List[Suggestion] = []
    for (kind, _), ms in groups.items():
        counted = [m for m in ms if not m.community_business]
        items = list(dict.fromkeys(i for m in ms for i in m.items))
        contexts = list(dict.fromkeys(m.context for m in ms if m.context))
        out.append(
            Suggestion(
                name=ms[0].name,
                kind=kind,
                topic=topic_for_kind(kind),
                thumbs_up=sum(m.polarity == "positive" for m in counted),
                thumbs_down=sum(m.polarity == "negative" for m in counted),
                last_date=max(m.date for m in ms),
                items=items,
                contexts=contexts,
                community_business=any(m.community_business for m in ms),
                mentions=ms,
            )
        )
    return sorted(out, key=lambda s: (s.kind.value, s.name))


def write_suggestions(path: Path, suggestions: List[Suggestion]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for s in suggestions:
            f.write(s.model_dump_json() + "\n")


def read_suggestions(path: Path) -> List[Suggestion]:
    with path.open(encoding="utf-8") as f:
        return [Suggestion.model_validate_json(x) for x in f if x.strip()]
