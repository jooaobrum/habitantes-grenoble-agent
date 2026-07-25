"""Background message pipeline for the WhatsApp Cloud API webhook.

Ported from the Baileys adapter's `app/whatsapp_bot/src/handlers.ts` (kept in
place, untouched). This is the channel's translation layer: inbound webhook
event -> guards -> agent turn -> reply. It holds NO agent logic itself (that
lives behind `run_chat_turn`, shared with the Telegram/HTTP channel) — it only
decides *whether* and *how* to relay.

Unlike the Node adapter, which calls the agent over HTTP (`api.ts`), this runs
*inside* the same FastAPI process as the agent — so `run_chat_turn` and
`reset_agent_memory` are called directly, no self-HTTP round trip.

Called from `routers/webhooks.py` as a `BackgroundTasks` job, one per inbound
message, *after* the webhook has already returned 200 to Meta (see that
module for why: Meta expects a fast ack, not a full agent turn).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from habitantes.config import WhatsAppCloudConfig, load_settings
from habitantes.domain import reset_agent_memory
from habitantes.infrastructure.api.routers.chat import Disabled, run_chat_turn
from habitantes.infrastructure.logging import get_feedback_logger
from habitantes.infrastructure.whatsapp.client import mark_read_and_typing, send_text
from habitantes.infrastructure.whatsapp.guards import (
    DedupSet,
    KeyedLock,
    RateLimiter,
    exceeds_length,
    hash_wa_id,
    is_gratitude_only,
    is_reset_command,
)

logger = logging.getLogger(__name__)

# Portuguese user-facing copy — kept identical to handlers.ts's COPY (and, by
# extension, to the Telegram channel's copy for the shared strings).
COPY = {
    "oversize": lambda max_length: (
        f"⚠️ Sua mensagem é muito longa (máximo {max_length} caracteres). "
        "Por favor, tente resumir sua pergunta."
    ),
    "throttle": (
        "⏳ Você enviou muitas mensagens em pouco tempo. "
        "Por favor, aguarde um minuto antes de perguntar novamente."
    ),
    # handlers.ts also has a distinct `apiError` for a failed HTTP call to a
    # separate API process. Not applicable here — the webhook runs in-process,
    # so an agent-turn failure is an unexpected exception, not a network error,
    # and collapses into tech_error below.
    "tech_error": "Ocorreu um erro técnico. Estamos trabalhando para resolver!",
    "gratitude": "De nada! 😊",
    "reset": "🔄 Prontinho! Comecei uma conversa nova — pode perguntar o que quiser. 😊",
    "feedback_ack": "Obrigado pelo seu feedback! 🙏",
}

# Emoji reactions that map to a rating on a bot answer (mirrors handlers.ts).
UP_EMOJI = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "❤️", "❤", "🙏", "🥰", "😍"}
DOWN_EMOJI = {"👎", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿"}

# Bound the feedback-correlation maps the same way handlers.ts / index.ts do
# (only clear once oversized — correlation only matters short-term).
_FEEDBACK_MAP_MAX_SIZE = 5000


@dataclass
class _ChannelState:
    """Process-lived, connection-independent state for the Cloud API channel.

    Mirrors `HandlerDeps` in the Baileys adapter's `index.ts`: one instance for
    the process lifetime, cleaned up periodically by the API's existing hourly
    cleanup task (see `main.py`'s `_cleanup_rate_limits`) rather than a second
    timer.
    """

    dedup: DedupSet = field(default_factory=DedupSet)
    rate_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(5, 60.0))
    locks: KeyedLock = field(default_factory=KeyedLock)
    # sent message id (wamid) -> chat_id, for reaction feedback.
    answer_to_chat: dict[str, str] = field(default_factory=dict)
    # wa_id -> last answered turn, for gratitude-word feedback.
    last_turn: dict[str, dict[str, str]] = field(default_factory=dict)

    def cleanup(self) -> None:
        self.dedup.clear()
        self.rate_limiter.cleanup()
        if len(self.answer_to_chat) > _FEEDBACK_MAP_MAX_SIZE:
            self.answer_to_chat.clear()
        if len(self.last_turn) > _FEEDBACK_MAP_MAX_SIZE:
            self.last_turn.clear()


_channel_state: _ChannelState | None = None


def get_channel_state() -> _ChannelState:
    """Lazy singleton, built from config on first use (rate_limiter's window
    needs `whatsapp_cloud.rate_limit_per_minute`)."""
    global _channel_state
    if _channel_state is None:
        cfg = load_settings().whatsapp_cloud
        _channel_state = _ChannelState(
            rate_limiter=RateLimiter(cfg.rate_limit_per_minute, 60.0)
        )
    return _channel_state


def format_reply(answer: str, sources: list) -> str:
    """Build the reply text: answer + an optional "Fontes" footer (top 3
    sources). Port of handlers.ts's `formatReply`; `sources` is the
    `ChatResponse.sources` list of `Source` pydantic models.
    """
    if not sources:
        return answer
    lines = []
    for s in sources[:3]:
        category = s.category or "Geral"
        # Web sources carry "{title} — {url}" in text_snippet — that's the
        # actual citation; category/date is empty for most web results.
        desc = (
            s.text_snippet or category
            if category.startswith("Web")
            else (f"{category} ({s.date or 'Recente'})")
        )
        lines.append(f"• {desc}")
    return f"{answer}\n\n📚 *Fontes:*\n" + "\n".join(lines)


async def handle_inbound_message(message: dict, cfg: WhatsAppCloudConfig) -> None:
    """Entry point scheduled by the webhook router for one inbound message
    (already dedup-checked). Dispatches on Meta's `type` field; anything
    other than text/reaction (image, audio, sticker, location, ...) is
    silently ignored — this bot is text-only.
    """
    try:
        msg_type = message.get("type")
        if msg_type == "reaction":
            await _handle_reaction(message, cfg)
        elif msg_type == "text":
            await _handle_text(message, cfg)
    except Exception:
        logger.exception("whatsapp_cloud: unhandled error processing inbound message")


async def _handle_text(message: dict, cfg: WhatsAppCloudConfig) -> None:
    wa_id = message.get("from")
    message_id = message.get("id")
    text = ((message.get("text") or {}).get("body") or "").strip()
    if not wa_id or not message_id or not text:
        return

    chat_id = hash_wa_id(wa_id, cfg.id_salt, cfg.id_hash_length)
    state = get_channel_state()

    # Gratitude short-circuit: a "thanks" on the last answered turn counts as
    # a 👍 and is NOT re-run through the agent.
    if is_gratitude_only(text, cfg.feedback_positive_keywords):
        turn = state.last_turn.get(wa_id)
        if turn:
            trace_id = str(uuid.uuid4())
            get_feedback_logger().log_feedback(
                chat_id=turn["chat_id"],
                message_id=turn["answer_message_id"],
                rating="up",
                trace_id=trace_id,
            )
            logger.info(
                "whatsapp_cloud: gratitude feedback recorded chat_id=%s", chat_id
            )
            await asyncio.to_thread(send_text, wa_id, COPY["gratitude"], cfg)
            return
        # No prior turn to attribute it to -> fall through and treat as a question.

    # Reset command ("/reset" or bare "reset") -> clear agent memory, confirm,
    # and stop — never reaches the agent, no rate-limit/length checks needed.
    if is_reset_command(text):
        reset_agent_memory(chat_id)
        logger.info("whatsapp_cloud: memory reset chat_id=%s", chat_id)
        await asyncio.to_thread(send_text, wa_id, COPY["reset"], cfg)
        return

    # Length cap -> ask to shorten; no agent call.
    if exceeds_length(text, cfg.max_message_length):
        await asyncio.to_thread(
            send_text, wa_id, COPY["oversize"](cfg.max_message_length), cfg
        )
        return

    # Per-user rate limit -> polite throttle; no agent call.
    if not state.rate_limiter.allow(wa_id):
        await asyncio.to_thread(send_text, wa_id, COPY["throttle"], cfg)
        return

    # Serialize per wa_id so one user is processed one message at a time.
    async def _answer() -> None:
        try:
            await asyncio.to_thread(mark_read_and_typing, message_id, cfg)

            trace_id = str(uuid.uuid4())
            result = await run_chat_turn(
                chat_id=chat_id, message=text, message_id=message_id, trace_id=trace_id
            )

            if isinstance(result, Disabled):
                await asyncio.to_thread(send_text, wa_id, result.message, cfg)
                return

            reply_text = format_reply(result.answer, result.sources)
            sent_id = await asyncio.to_thread(send_text, wa_id, reply_text, cfg)

            if sent_id:
                state.answer_to_chat[sent_id] = chat_id
                state.last_turn[wa_id] = {
                    "chat_id": chat_id,
                    "answer_message_id": sent_id,
                }
            logger.info(
                "whatsapp_cloud: answer delivered chat_id=%s trace_id=%s cached=%s",
                chat_id,
                trace_id,
                getattr(result, "cached", False),
            )
        except Exception:
            logger.exception(
                "whatsapp_cloud: unexpected error handling message chat_id=%s", chat_id
            )
            await asyncio.to_thread(send_text, wa_id, COPY["tech_error"], cfg)

    await state.locks.run(wa_id, _answer)


async def _handle_reaction(message: dict, cfg: WhatsAppCloudConfig) -> None:
    """Map a reaction on one of our answers to a feedback rating."""
    reaction = message.get("reaction") or {}
    reacted_id = reaction.get("message_id")
    emoji = reaction.get("emoji", "")
    wa_id = message.get("from")
    if not reacted_id or not wa_id:
        return

    state = get_channel_state()
    chat_id = state.answer_to_chat.get(reacted_id)
    if not chat_id:
        return  # not one of our answers

    rating: str | None = None
    if emoji in UP_EMOJI:
        rating = "up"
    elif emoji in DOWN_EMOJI:
        rating = "down"
    if not rating:
        return  # reaction removed, or an emoji we don't map

    trace_id = str(uuid.uuid4())
    get_feedback_logger().log_feedback(
        chat_id=chat_id, message_id=reacted_id, rating=rating, trace_id=trace_id
    )
    logger.info(
        "whatsapp_cloud: reaction feedback recorded chat_id=%s rating=%s",
        chat_id,
        rating,
    )
    await asyncio.to_thread(send_text, wa_id, COPY["feedback_ack"], cfg)
