"""Pure guard/utility functions for the WhatsApp Cloud API channel.

Originally ported from the pre-migration WhatsApp adapter's guard logic;
kept for chat_id continuity with users who joined before the migration to
the official Cloud API. Every function here is side-effect-free except the
two small in-memory state classes (`RateLimiter`, `DedupSet`).

Not ported: `isDirectMessage` / the DM-only firewall. The Cloud API only ever
delivers 1:1 business-number traffic — groups cannot reach a WhatsApp Business
number at all — so that guard has no analogue here.
"""

import asyncio
import re
import unicodedata
from hashlib import sha256
from time import monotonic
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

# ASCII punctuation ranges to collapse to whitespace during normalization:
# !-/  :-@  [-`  {-~   (matches the pre-migration adapter's
# `[!-/:-@[-\`{-~]+`). Deliberately excludes digits/letters and leaves
# non-ASCII (accented letters after stripping, emoji) untouched.
_ASCII_PUNCT_RE = re.compile(r"[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]+")
_WHITESPACE_RE = re.compile(r"\s+")


def hash_wa_id(wa_id: str, salt: str, hash_length: int) -> str:
    """Deterministic one-way hash of a Cloud API `wa_id` -> the `chat_id`.

    `sha256(salt + wa_id)`, hex, truncated to `hash_length`. `wa_id` (as
    delivered by Meta's webhook, e.g. "553199999999") is already the bare
    digits the pre-migration adapter derived from the JID — so no stripping
    step is needed here. Using the same salt across the migration
    (WHATSAPP_ID_SALT) means a returning user resolves to the same `chat_id`
    they had before the migration.
    """
    digest = sha256((salt + wa_id).encode("utf-8")).hexdigest()
    return digest[:hash_length]


def normalize_text(text: str) -> str:
    """Lowercase, strip accents/diacritics, collapse ASCII punctuation to
    spaces, and trim. Emoji and other non-ASCII symbols are preserved (not
    stripped wholesale) — gratitude keywords like "🙏" must survive matching.
    """
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = without_marks.lower()
    despunctuated = _ASCII_PUNCT_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", despunctuated).strip()


def is_gratitude_only(text: str, keywords: list[str]) -> bool:
    """True when the message is essentially only gratitude (a 'thanks').

    After normalizing, the message must be short (<= 4 tokens) AND either the
    whole normalized string is a keyword, or every token is a keyword. A real
    question ("obrigado, mas e o visto?") returns False — it carries
    non-gratitude tokens.
    """
    normalized = normalize_text(text)
    if not normalized:
        return False

    keyword_set = {k for k in (normalize_text(kw) for kw in keywords) if k}
    if not keyword_set:
        return False

    # Whole-message match handles multi-word keywords ("thank you", "muito obrigado").
    if normalized in keyword_set:
        return True

    tokens = normalized.split(" ")
    if len(tokens) > 4:
        return False

    return all(token in keyword_set for token in tokens)


def is_reset_command(text: str) -> bool:
    """True when the message is (only) the reset command — `/reset` or bare
    `reset`, case/accent-insensitive. `normalize_text` already strips a
    leading `/` (ASCII punctuation), so both forms collapse to the same check.
    """
    return normalize_text(text) == "reset"


def exceeds_length(text: str, max_length: int) -> bool:
    """True when the text is longer than the allowed maximum."""
    return len(text) > max_length


class RateLimiter:
    """Sliding-window per-key rate limiter (mirrors Telegram's per-chat throttle).

    `allow(key)` prunes timestamps older than the window, then rejects
    (without recording) if the key is already at `max_per_window`; otherwise
    records "now" and allows. `cleanup()` drops empty/expired keys to bound
    memory growth.
    """

    def __init__(self, max_per_window: int, window_seconds: float = 60.0) -> None:
        self._max_per_window = max_per_window
        self._window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = monotonic()
        cutoff = now - self._window_seconds
        recent = [ts for ts in self._hits.get(key, []) if ts > cutoff]

        if len(recent) >= self._max_per_window:
            self._hits[key] = recent
            return False

        recent.append(now)
        self._hits[key] = recent
        return True

    def cleanup(self) -> None:
        cutoff = monotonic() - self._window_seconds
        for key in list(self._hits.keys()):
            recent = [ts for ts in self._hits[key] if ts > cutoff]
            if not recent:
                del self._hits[key]
            else:
                self._hits[key] = recent


class DedupSet:
    """In-memory dedup set keyed by the WhatsApp `message.id`.

    Meta retries webhook delivery on anything but a fast 200, so this makes
    processing idempotent. Kept as a class (not a bare set) so the periodic
    cleanup task can `clear()` it.
    """

    def __init__(self) -> None:
        self._ids: set[str] = set()

    def has(self, message_id: str) -> bool:
        return message_id in self._ids

    def add(self, message_id: str) -> None:
        self._ids.add(message_id)

    def clear(self) -> None:
        self._ids.clear()

    def __len__(self) -> int:
        return len(self._ids)


class KeyedLock:
    """Per-key serial lock so one wa_id is processed one message at a time.

    Guards against a real race: two rapid messages from the same user can
    arrive as two separate webhook POSTs, each scheduled as an independent
    `BackgroundTasks` job, which can then interleave on the event loop and
    corrupt the per-`chat_id` agent memory dict (`domain/agent.py`'s
    `_memory`) if processed concurrently.

    Keeps one `asyncio.Lock` per key for the process lifetime (rather than
    dropping a key's lock once idle) — acceptable at this project's scale
    (~100 users, see docs/OVERVIEW.md).
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    async def run(self, key: str, fn: Callable[[], Awaitable[T]]) -> T:
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await fn()
