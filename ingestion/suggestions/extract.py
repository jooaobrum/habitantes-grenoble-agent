"""Pseudonymisation and LLM extraction of Mentions from one window.

Authors become M1, M2... before any text leaves this module; phone numbers are
scrubbed from input and output. The extraction LLM is called over HTTP
(OpenRouter chat completions, JSON-schema output) with an injectable client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from habitantes.domain.suggestions import Kind
from ingestion.suggestions.windows import Window

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"(?<!\w)\+?\d(?:[\s.\-()]?\d){7,14}(?!\w)")
PHONE_PLACEHOLDER = "[telefone]"


class Mention(BaseModel):
    """One member's opinion of one Suggestion. Deliberately has no author field."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Kind
    polarity: str = Field(pattern="^(positive|negative)$")
    items: List[str] = []
    context: str
    date: date
    community_business: bool = False


EXCLUDED_ENTITY_TYPES = frozenset(
    {
        "private_individual",
        "bank",
        "phone_operator",
        "app",
        "association",
        "public_service",
        "one_off_event",
    }
)
ENTITY_TYPES = ["business", "place", "product", *sorted(EXCLUDED_ENTITY_TYPES)]


class _RawMention(BaseModel):
    """LLM output shape (unknown keys such as an author are ignored)."""

    name: str
    kind: str
    polarity: str
    items: List[str] = []
    context: str = ""
    date: Optional[str] = None
    community_business: bool = False
    business_identity: bool = False
    entity_type: str = "business"


class _RawMentions(BaseModel):
    mentions: List[_RawMention] = []


def scrub_phones(text: str) -> str:
    return _PHONE_RE.sub(PHONE_PLACEHOLDER, text)


def pseudonymise(window: Window) -> tuple[str, Dict[str, str]]:
    """Render the window as `date | Mk: text` lines; return (text, user->pseudonym)."""
    pseudo: Dict[str, str] = {}
    for m in window.messages:
        pseudo.setdefault(str(m["user"]), f"M{len(pseudo) + 1}")
    lines: List[str] = []
    for m in window.messages:
        body = str(m["message"])
        for user, tag in sorted(pseudo.items(), key=lambda kv: -len(kv[0])):
            if len(user) >= 3 and not user.startswith("+"):
                body = re.sub(re.escape(user), tag, body, flags=re.IGNORECASE)
        body = scrub_phones(body).replace("\n", " ")
        day = str(m["timestamp"])[:10]
        lines.append(f"{day} | {pseudo[str(m['user'])]}: {body}")
    return "\n".join(lines), pseudo


EXTRACTION_PROMPT = """Você extrai Menções de negócios, lugares e produtos de um trecho de um grupo de WhatsApp de brasileiros em Grenoble. Os autores aparecem como M1, M2... (pseudônimos).

Uma Menção é a opinião positiva ou negativa de UMA pessoa sobre UM negócio/lugar/produto. Várias mensagens seguidas da mesma pessoa sobre o mesmo lugar são UMA só Menção.
Regras:
- name: nome do negócio (para redes, o nome da rede, não da filial).
- kind: um de {kinds}.
- polarity: "positive" ou "negative".
- items: produtos/serviços específicos pelos quais foi citado (ex.: massa de pastel, limpeza dental).
- context: UMA frase reescrita (o que é bom/ruim e por quê). Nunca copie a mensagem; nunca cite M1, M2 nem telefones.
- date: data (AAAA-MM-DD) da mensagem da Menção.
- entity_type: business, place ou product para o que entra; para o que NÃO entra use private_individual (pessoa física), bank, phone_operator, app, association, public_service ou one_off_event (evento pontual).
- community_business: true se a pessoa divulga o próprio negócio (post de divulgação própria).
- business_identity: só relevante quando community_business é true; true APENAS se o texto mostra identidade de negócio além do nome ou telefone pessoal: nome comercial MAIS perfil profissional em rede social, site ou página de reservas. Nome da pessoa, telefone pessoal ou apenas ser membro do grupo NÃO bastam (false).
Ignore pessoas físicas, bancos, operadoras de telefone, aplicativos, associações, serviços públicos e eventos pontuais. Sem Menções, devolva lista vazia.
Responda em JSON: {{"mentions": [...]}}.

Trecho:
{text}
"""


def _schema() -> Dict[str, Any]:
    return {
        "name": "mentions",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["mentions"],
            "properties": {
                "mentions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "name",
                            "kind",
                            "polarity",
                            "items",
                            "context",
                            "date",
                            "community_business",
                            "business_identity",
                            "entity_type",
                        ],
                        "properties": {
                            "name": {"type": "string"},
                            "kind": {"type": "string", "enum": [k.value for k in Kind]},
                            "polarity": {
                                "type": "string",
                                "enum": ["positive", "negative"],
                            },
                            "items": {"type": "array", "items": {"type": "string"}},
                            "context": {"type": "string"},
                            "date": {"type": "string"},
                            "community_business": {"type": "boolean"},
                            "business_identity": {"type": "boolean"},
                            "entity_type": {"type": "string", "enum": ENTITY_TYPES},
                        },
                    },
                }
            },
        },
    }


def _to_mention(raw: _RawMention, fallback: date) -> Optional[Mention]:
    if raw.entity_type in EXCLUDED_ENTITY_TYPES:
        return None
    if raw.community_business and not raw.business_identity:
        # own-business post without a business identity: not a Community Business
        return None
    try:
        when = datetime.strptime((raw.date or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        when = fallback
    try:
        return Mention(
            name=scrub_phones(raw.name).strip(),
            kind=Kind(raw.kind),
            polarity=raw.polarity,
            items=[scrub_phones(i).strip() for i in raw.items if i.strip()],
            context=scrub_phones(raw.context).strip(),
            date=when,
            community_business=raw.community_business,
        )
    except (ValidationError, ValueError) as e:
        logger.warning("Dropping malformed Mention %r: %s", raw.name, e)
        return None


async def extract_mentions(
    client: httpx.AsyncClient,
    window: Window,
    api_key: Optional[str] = None,
    model: str = "google/gemini-2.5-flash-lite",
    base_url: str = "https://openrouter.ai/api/v1",
    temperature: float = 0.0,
    max_retries: int = 4,
    retry_base_sleep_s: float = 1.5,
    timeout_s: float = 60.0,
) -> Optional[List[Mention]]:
    """Mentions of one window, or None when the call failed (never raises)."""
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        logger.error("OPENROUTER_API_KEY not set; window not extracted")
        return None
    text, _ = pseudonymise(window)
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {
                "role": "user",
                "content": EXTRACTION_PROMPT.format(
                    kinds=", ".join(k.value for k in Kind), text=text
                ),
            }
        ],
        "response_format": {"type": "json_schema", "json_schema": _schema()},
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    fallback = _first_date(window)
    for attempt in range(max_retries):
        try:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout_s,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            raw = _RawMentions.model_validate(json.loads(content))
            found = [_to_mention(r, fallback) for r in raw.mentions]
            return [m for m in found if m]
        except Exception as e:
            permanent = (
                isinstance(e, httpx.HTTPStatusError)
                and 400 <= e.response.status_code < 500
                and e.response.status_code not in (408, 429)
            )
            if permanent or attempt == max_retries - 1:
                logger.error(
                    "Final extraction failure for thread %s: %s", window.thread_id, e
                )
                return None
            await asyncio.sleep(
                (retry_base_sleep_s**attempt) + random.uniform(0, 0.5)
                if retry_base_sleep_s
                else 0
            )
    return None


def _first_date(window: Window) -> date:
    return datetime.strptime(
        str(window.messages[0]["timestamp"])[:10], "%Y-%m-%d"
    ).date()
