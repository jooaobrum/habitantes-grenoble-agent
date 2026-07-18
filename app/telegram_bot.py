import asyncio
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    constants,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Add the api/src to the python path so we can import habitantes.config
# Assuming the root is 1 level above app/
root_dir = Path(__file__).parents[1]
sys.path.append(str(root_dir / "api" / "src"))

from habitantes.config import load_settings  # noqa: E402

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Settings
settings = load_settings()
API_URL = settings.telegram.api_url
BOT_TOKEN = settings.telegram.bot_token
ADMIN_TOKEN = settings.admin.token
HEARTBEAT_INTERVAL_SECONDS = 30

# Kept identical to the WhatsApp channel's COPY.reset (app/whatsapp_bot/src/handlers.ts).
RESET_CONFIRMATION = (
    "🔄 Prontinho! Comecei uma conversa nova — pode perguntar o que quiser. 😊"
)

# Per-chat locks to avoid race conditions
_chat_locks = defaultdict(asyncio.Lock)
# Simple message deduplication
_processed_messages: set[str] = set()
# Rate limiting
_user_last_messages = defaultdict(list)


async def _cleanup_processed_messages():
    """Periodically clear old processed message IDs to prevent memory leaks."""
    while True:
        await asyncio.sleep(3600)  # Every hour
        _processed_messages.clear()
        _user_last_messages.clear()


async def _send_heartbeat():
    """Post a heartbeat to the API on the bot's own poll loop.

    Best-effort: a failed heartbeat never crashes the bot. Missed heartbeats
    surface on their own — `check_telegram_heartbeat` in `health_checks.py`
    flips the bot to `critical` once the staleness window elapses.
    """
    while True:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{API_URL}/admin/heartbeat",
                    json={"service": "telegram_bot"},
                    headers={"X-Admin-Token": ADMIN_TOKEN},
                )
                if response.status_code != 200:
                    logger.warning(
                        "Heartbeat rejected (%s): %s",
                        response.status_code,
                        response.text,
                    )
        except Exception:
            logger.exception("Failed to post heartbeat")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    welcome_text = (
        "Olá! Sou o assistente para brasileiros em Grenoble. 🇧🇷🇫🇷\n\n"
        "Posso te ajudar com dúvidas sobre vistos, moradia, saúde, "
        "trabalho, universidade e muito mais.\n\n"
        "Basta me enviar sua pergunta!"
    )
    await update.message.reply_text(welcome_text)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset command: clear this chat's agent-side memory."""
    chat_id = str(update.effective_chat.id)

    try:
        async with httpx.AsyncClient(
            timeout=float(settings.api.request_timeout_seconds)
        ) as client:
            response = await client.post(
                f"{API_URL}/chat/reset",
                json={"chat_id": chat_id},
                headers={"X-Chat-Id": chat_id},
            )
        if response.status_code != 200:
            logger.error(f"Reset API Error ({response.status_code}): {response.text}")
            await update.message.reply_text(
                "Desculpe, tive um problema ao reiniciar a conversa. "
                "Por favor, tente novamente em instantes."
            )
            return
    except Exception:
        logger.exception("Unexpected error in reset")
        await update.message.reply_text(
            "Ocorreu um erro técnico. Estamos trabalhando para resolver!"
        )
        return

    await update.message.reply_text(RESET_CONFIRMATION)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle plain text messages by calling the FastAPI agent."""
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    message_text = update.message.text
    message_id = str(update.message.message_id)

    # 1. Length validation
    max_len = settings.telegram.max_message_length
    if len(message_text) > max_len:
        await update.message.reply_text(
            f"⚠️ Sua mensagem é muito longa (máximo {max_len} caracteres). "
            "Por favor, tente resumir sua pergunta."
        )
        return

    # 2. Rate limiting (simple)
    now = time.time()
    recent = [t for t in _user_last_messages[chat_id] if now - t < 60]
    _user_last_messages[chat_id] = recent
    if len(recent) >= settings.telegram.rate_limit_per_minute:
        await update.message.reply_text(
            "⏳ Você enviou muitas mensagens em pouco tempo. "
            "Por favor, aguarde um minuto antes de perguntar novamente."
        )
        return
    _user_last_messages[chat_id].append(now)

    # 3. Deduplicate
    unique_id = f"{chat_id}_{message_id}"
    if unique_id in _processed_messages:
        return
    _processed_messages.add(unique_id)

    # Ensure we only process one message per chat at a time
    async with _chat_locks[chat_id]:
        # Show typing status
        await context.bot.send_chat_action(
            chat_id=chat_id, action=constants.ChatAction.TYPING
        )

        try:
            async with httpx.AsyncClient(
                timeout=float(settings.api.request_timeout_seconds + 5)
            ) as client:
                request_body = {
                    "chat_id": str(chat_id),
                    "message": message_text,
                    "message_id": message_id,
                }
                headers = {"X-Chat-Id": str(chat_id)}

                response = await client.post(
                    f"{API_URL}/chat/", json=request_body, headers=headers
                )

                if response.status_code != 200:
                    logger.error(f"API Error ({response.status_code}): {response.text}")
                    await update.message.reply_text(
                        "Desculpe, tive um problema ao processar sua pergunta. "
                        "Por favor, tente novamente em instantes."
                    )
                    return

                data = response.json()
                answer = data.get("answer", "")
                sources = data.get("sources", [])

                # Format final message
                final_text = answer

                if sources:
                    source_links = []
                    for s in sources[:3]:
                        category = s.get("category") or "Geral"
                        if category.startswith("Web"):
                            # Web sources carry "{title} — {url}" in text_snippet —
                            # that's the actual citation; category/date is empty
                            # for most web results and isn't useful alone.
                            desc = s.get("text_snippet") or category
                        else:
                            desc = f"{category} ({s.get('date') or 'Recente'})"
                        source_links.append(f"• {desc}")

                    if source_links:
                        final_text += "\n\n📚 *Fontes:*\n" + "\n".join(source_links)

                feedback_keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("👍", callback_data="fb:up"),
                            InlineKeyboardButton("👎", callback_data="fb:down"),
                        ]
                    ]
                )
                await update.message.reply_text(
                    final_text,
                    parse_mode=constants.ParseMode.MARKDOWN,
                    reply_markup=feedback_keyboard,
                )
        except Exception:
            logger.exception("Unexpected error in handle_message")
            await update.message.reply_text(
                "Ocorreu um erro técnico. Estamos trabalhando para resolver!"
            )


async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 👍/👎 taps by POSTing the rating to the API feedback endpoint."""
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("fb:"):
        return

    rating = query.data.split(":", 1)[1]  # "up" or "down"
    chat_id = str(update.effective_chat.id)
    message_id = str(query.message.message_id)

    try:
        async with httpx.AsyncClient(
            timeout=float(settings.api.request_timeout_seconds)
        ) as client:
            response = await client.post(
                f"{API_URL}/feedback/",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "rating": rating,
                },
                headers={"X-Chat-Id": chat_id},
            )
        if response.status_code != 200:
            logger.error(
                f"Feedback API Error ({response.status_code}): {response.text}"
            )
            await query.answer("Não foi possível registrar seu feedback.")
            return
    except Exception:
        logger.exception("Unexpected error in handle_feedback")
        await query.answer("Não foi possível registrar seu feedback.")
        return

    await query.answer("Obrigado pelo seu feedback! 🙏")
    await query.edit_message_reply_markup(reply_markup=None)


async def post_init(application):
    """Start background tasks."""
    asyncio.create_task(_cleanup_processed_messages())
    asyncio.create_task(_send_heartbeat())


def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment settings!")
        sys.exit(1)

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    start_handler = CommandHandler("start", start)
    reset_handler = CommandHandler("reset", reset)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)

    feedback_handler = CallbackQueryHandler(handle_feedback, pattern=r"^fb:")

    application.add_handler(start_handler)
    application.add_handler(reset_handler)
    application.add_handler(message_handler)
    application.add_handler(feedback_handler)

    logger.info("Bot starting...")
    application.run_polling()


if __name__ == "__main__":
    main()
