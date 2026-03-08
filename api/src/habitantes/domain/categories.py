"""Category helpers — pure functions, no I/O.

Single source of truth for category data lives in config/base.yaml.
This module provides helpers that consume that data.
"""

from habitantes.config import CategoryEntry, load_settings

_EMOJIS = [
    "🛂",
    "🏦",
    "🏠",
    "🏥",
    "🎓",
    "💼",
    "📋",
    "🛒",
    "🚌",
    "🗣️",
    "⛷️",
    "🍽️",
    "⚽",
    "🎉",
    "🏘️",
    "🛍️",
    "💇",
    "🐾",
    "📱",
]

# ── Lazy loader ───────────────────────────────────────────────────────────────

_categories_cache: list[CategoryEntry] | None = None


def _get_categories() -> list[CategoryEntry]:
    global _categories_cache
    if _categories_cache is None:
        _categories_cache = load_settings().categories
    return _categories_cache


# ── Pure helpers ──────────────────────────────────────────────────────────────


def build_greeting_text(categories: list[CategoryEntry]) -> str:
    """Build the numbered category menu shown on greeting."""
    lines = []
    for i, cat in enumerate(categories, 1):
        emoji = _EMOJIS[i - 1] if i - 1 < len(_EMOJIS) else "•"
        lines.append(f"{i}. {emoji} {cat.pt_name}")
    body = "\n".join(lines)
    return (
        "Olá! Sou o assistente dos *Habitantes de Grenoble*. 👋\n\n"
        "Posso ajudar com dúvidas sobre a vida de brasileiros em Grenoble. "
        "Primeiramente, sobre qual tema você gostaria de perguntar?\n\n"
        f"{body}\n\n"
        "Digite o número do tema ou faça sua pergunta diretamente!"
    )


def resolve_number(
    message: str, categories: list[CategoryEntry]
) -> CategoryEntry | None:
    """Return CategoryEntry if message is a valid category number, else None."""
    stripped = message.strip()
    if not stripped.isdigit():
        return None
    n = int(stripped)
    if 1 <= n <= len(categories):
        return categories[n - 1]
    return None


def get_by_en_name(
    en_name: str, categories: list[CategoryEntry]
) -> CategoryEntry | None:
    """Look up a CategoryEntry by its English name."""
    for cat in categories:
        if cat.en_name == en_name:
            return cat
    return None
