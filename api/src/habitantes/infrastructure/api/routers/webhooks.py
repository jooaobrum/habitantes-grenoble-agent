"""WhatsApp Cloud API webhook — the inbound half of the official channel.

Two verbs on the same path, per Meta's contract:

- `GET  /webhooks/whatsapp` — the one-time (and per-reconfiguration) handshake
  Meta performs when you save the webhook URL in the app dashboard.
- `POST /webhooks/whatsapp` — every inbound event: messages, reactions, and
  status callbacks (delivered/read receipts, which we ignore).

The POST handler's only job is: verify the signature, dedup, schedule the real
work, and return 200 *fast*. Meta expects an ack within a few seconds and
retries (redelivering the same event) on anything else — since the agent
turn behind this is an LLM + vector search call that can take much longer,
processing inline would cause duplicate answers at double the LLM cost. See
`infrastructure/whatsapp/processor.py` for the actual message pipeline, run
via `BackgroundTasks` after this returns.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import PlainTextResponse

from habitantes.config import load_settings
from habitantes.infrastructure.whatsapp import processor

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> PlainTextResponse:
    cfg = load_settings().whatsapp_cloud

    if (
        hub_mode == "subscribe"
        and cfg.verify_token
        and hmac.compare_digest(hub_verify_token, cfg.verify_token)
    ):
        # Meta requires the raw challenge back as plain text, NOT JSON —
        # a quoted string fails verification.
        return PlainTextResponse(hub_challenge)

    logger.warning("whatsapp webhook: verification failed (mode=%s)", hub_mode)
    return PlainTextResponse("forbidden", status_code=403)


@router.post("/whatsapp")
async def receive_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> PlainTextResponse:
    cfg = load_settings().whatsapp_cloud

    # Read the raw body BEFORE any parsing — signature verification is over
    # the exact bytes Meta sent, not a round-tripped re-serialization.
    raw_body = await request.body()
    signature_header = request.headers.get("x-hub-signature-256", "")
    if not _verify_signature(raw_body, signature_header, cfg.app_secret):
        logger.warning("whatsapp webhook: signature verification failed")
        return PlainTextResponse("forbidden", status_code=403)

    try:
        payload = await request.json()
    except Exception:
        # Malformed body from a source that just proved it holds our app
        # secret — log and ack anyway; nothing more we can do with it, and a
        # non-200 here would just cause Meta to retry the same bad payload.
        logger.warning("whatsapp webhook: failed to parse JSON body")
        return PlainTextResponse("ok")

    state = processor.get_channel_state()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                message_id = message.get("id")
                if not message_id or state.dedup.has(message_id):
                    continue
                # Dedup synchronously, before scheduling — a Meta retry of an
                # already-seen id must never enqueue a second agent turn.
                state.dedup.add(message_id)
                background_tasks.add_task(
                    processor.handle_inbound_message, message, cfg
                )
            # value.get("statuses", []) — delivery/read receipts — intentionally
            # ignored; the 200 below still acks them so Meta doesn't retry.

    return PlainTextResponse("ok")


def _verify_signature(raw_body: bytes, header_value: str, app_secret: str) -> bool:
    """Verify Meta's `X-Hub-Signature-256` HMAC over the raw request body.

    Without this, anyone who discovers the webhook URL could inject fake
    messages into the agent. Fails closed: an unset `app_secret` (channel not
    yet configured) or a missing/malformed header both verify as False.
    """
    if not app_secret or not header_value.startswith("sha256="):
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    provided = header_value[len("sha256=") :]
    return hmac.compare_digest(expected, provided)
