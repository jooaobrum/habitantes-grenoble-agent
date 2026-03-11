import asyncio
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx
from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    welcome_text = (
        "Olá! Sou o assistente para brasileiros em Grenoble. 🇧🇷🇫🇷\n\n"
        "Posso te ajudar com dúvidas sobre vistos, moradia, saúde, "
        "trabalho, universidade e muito mais.\n\n"
        "Basta me enviar sua pergunta!"
    )
    await update.message.reply_text(welcome_text)


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
                        # Using category/date as source description
                        desc = f"{s.get('category') or 'Geral'} ({s.get('date') or 'Recente'})"
                        source_links.append(f"• {desc}")

                    if source_links:
                        final_text += "\n\n📚 *Fontes:*\n" + "\n".join(source_links)

                await update.message.reply_text(
                    final_text, parse_mode=constants.ParseMode.MARKDOWN
                )
        except Exception:
            logger.exception("Unexpected error in handle_message")
            await update.message.reply_text(
                "Ocorreu um erro técnico. Estamos trabalhando para resolver!"
            )


async def post_init(application):
    """Start background tasks."""
    asyncio.create_task(_cleanup_processed_messages())


def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment settings!")
        sys.exit(1)

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    start_handler = CommandHandler("start", start)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)

    application.add_handler(start_handler)
    application.add_handler(message_handler)

    logger.info("Bot starting...")
    application.run_polling()


if __name__ == "__main__":
    main()
