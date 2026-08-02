"""Thin client for the WhatsApp Cloud API (Graph API `/messages` endpoint).

Mirrors the synchronous-httpx, fail-soft style of
`domain/tools/web_search.py` — every call swallows its own exception, logs,
and returns a sentinel (`None` / `False`) rather than raising. A send failure
must never crash the webhook's background processing of one user's turn.
"""

import logging

import httpx

from habitantes.config import WhatsAppCloudConfig

logger = logging.getLogger(__name__)


def _messages_url(cfg: WhatsAppCloudConfig) -> str:
    return (
        f"{cfg.graph_api_base}/{cfg.graph_api_version}/{cfg.phone_number_id}/messages"
    )


def _headers(cfg: WhatsAppCloudConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {cfg.access_token}"}


def send_text(wa_id: str, body: str, cfg: WhatsAppCloudConfig) -> str | None:
    """Send a plain-text WhatsApp message. Returns the sent message's Meta id
    (`wamid...`) for feedback correlation (reactions), or `None` on failure —
    never raises.
    """
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    try:
        response = httpx.post(
            _messages_url(cfg),
            headers=_headers(cfg),
            json=payload,
            timeout=cfg.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data["messages"][0]["id"]
    except Exception as exc:
        logger.warning("whatsapp_cloud: failed to send text: %s", exc)
        return None


def mark_read_and_typing(message_id: str, cfg: WhatsAppCloudConfig) -> bool:
    """Mark an inbound message as read and show the typing indicator. The
    indicator auto-clears when the reply lands or after 25s — there is no
    separate "stop typing" call to make (unlike a presence-update-based
    adapter, which must explicitly clear the indicator).
    Best-effort: failure here should never block answering the user.
    """
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        response = httpx.post(
            _messages_url(cfg),
            headers=_headers(cfg),
            json=payload,
            timeout=cfg.request_timeout_seconds,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("whatsapp_cloud: failed to mark read/typing: %s", exc)
        return False
