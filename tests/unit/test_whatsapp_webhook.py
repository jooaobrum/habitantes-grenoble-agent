"""Unit tests for the WhatsApp Cloud API webhook (routers/webhooks.py +
infrastructure/whatsapp/processor.py).

Exercises the full inbound path through `TestClient` (which runs
`BackgroundTasks` synchronously before `client.post(...)` returns), with the
outbound Graph API calls (`processor.send_text` / `mark_read_and_typing`) and
the agent turn (`processor.run_chat_turn`) mocked — mirrors how
`test_chat_gate.py` / `test_fail_open.py` mock `run_agent` for the HTTP
channel.
"""

import hashlib
import hmac
import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from habitantes.config import load_settings
from habitantes.infrastructure import control_store as cs
from habitantes.infrastructure.api.main import app
from habitantes.infrastructure.whatsapp import processor

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
PHONE_NUMBER_ID = "999888777"
ID_SALT = "test-id-salt"
WA_ID = "553199999999"

_ENV = {
    "WHATSAPP_APP_SECRET": APP_SECRET,
    "WHATSAPP_VERIFY_TOKEN": VERIFY_TOKEN,
    "WHATSAPP_PHONE_NUMBER_ID": PHONE_NUMBER_ID,
    "WHATSAPP_ID_SALT": ID_SALT,
    "WHATSAPP_BUSINESS_TOKEN": "test-token",
}


def _sign(raw: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _text_payload(message_id: str, body: str, wa_id: str = WA_ID) -> dict:
    return {
        "entry": [
            {
                "id": "waba1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "contacts": [{"wa_id": wa_id}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": message_id,
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ]
    }


def _reaction_payload(
    message_id: str, reacted_message_id: str, emoji: str, wa_id: str = WA_ID
) -> dict:
    return {
        "entry": [
            {
                "id": "waba1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": message_id,
                                    "timestamp": str(int(time.time())),
                                    "type": "reaction",
                                    "reaction": {
                                        "message_id": reacted_message_id,
                                        "emoji": emoji,
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ]
    }


class FakeSource:
    def __init__(self, category="Visa & Residency", date="", text_snippet=""):
        self.category = category
        self.date = date
        self.text_snippet = text_snippet


class FakeResult:
    def __init__(self, answer="Você precisa ir ao consulado.", sources=None):
        self.answer = answer
        self.sources = sources if sources is not None else [FakeSource()]
        self.cached = False


class WhatsAppWebhookTestCase(unittest.TestCase):
    """Common setup: env secrets, a fresh channel-state singleton per test,
    an enabled control-store switch, and a TestClient."""

    def setUp(self):
        self._env_patcher = patch.dict("os.environ", _ENV)
        self._env_patcher.start()
        load_settings.cache_clear()

        # Fresh dedup/rate-limiter/locks/feedback maps per test.
        processor._channel_state = None

        self._tmp = TemporaryDirectory()
        self.db = Path(self._tmp.name) / "control.db"
        cs.init_db(self.db)
        cs.set_switch(True, "test", self.db)
        self._db_patcher = patch.object(cs, "DEFAULT_DB_PATH", self.db)
        self._db_patcher.start()
        cs._invalidate_enabled_cache()

        self.client = TestClient(app)

    def tearDown(self):
        self._db_patcher.stop()
        cs._invalidate_enabled_cache()
        self._tmp.cleanup()
        processor._channel_state = None
        self._env_patcher.stop()
        load_settings.cache_clear()

    def _post(self, payload: dict, secret: str = APP_SECRET):
        raw = json.dumps(payload).encode()
        return self.client.post(
            "/webhooks/whatsapp",
            content=raw,
            headers={"x-hub-signature-256": _sign(raw, secret)},
        )


class TestHandshake(WhatsAppWebhookTestCase):
    def test_correct_token_returns_challenge_as_plain_text(self):
        resp = self.client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "abc123")

    def test_wrong_token_returns_403(self):
        resp = self.client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "abc123",
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_unset_verify_token_rejects_everything(self):
        with patch.dict("os.environ", {**_ENV, "WHATSAPP_VERIFY_TOKEN": ""}):
            load_settings.cache_clear()
            resp = self.client.get(
                "/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "",
                    "hub.challenge": "abc123",
                },
            )
        load_settings.cache_clear()
        self.assertEqual(resp.status_code, 403)


class TestSignatureVerification(WhatsAppWebhookTestCase):
    def test_missing_signature_header_returns_403(self):
        raw = json.dumps(_text_payload("wamid.1", "oi")).encode()
        resp = self.client.post("/webhooks/whatsapp", content=raw)
        self.assertEqual(resp.status_code, 403)

    def test_tampered_body_returns_403(self):
        payload = _text_payload("wamid.1", "oi")
        raw = json.dumps(payload).encode()
        signature = _sign(raw)
        tampered = json.dumps({**payload, "extra": "x"}).encode()
        resp = self.client.post(
            "/webhooks/whatsapp",
            content=tampered,
            headers={"x-hub-signature-256": signature},
        )
        self.assertEqual(resp.status_code, 403)

    def test_signature_computed_with_wrong_secret_returns_403(self):
        resp = self._post(_text_payload("wamid.1", "oi"), secret="not-the-real-secret")
        self.assertEqual(resp.status_code, 403)

    def test_unset_app_secret_rejects_everything(self):
        with patch.dict("os.environ", {**_ENV, "WHATSAPP_APP_SECRET": ""}):
            load_settings.cache_clear()
            resp = self._post(_text_payload("wamid.1", "oi"))
        load_settings.cache_clear()
        self.assertEqual(resp.status_code, 403)


class TestMessagePipeline(WhatsAppWebhookTestCase):
    def test_valid_message_gets_agent_reply_with_sources_footer(self):
        with (
            patch.object(
                processor, "send_text", return_value="wamid.SENT1"
            ) as mock_send,
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch.object(processor, "run_chat_turn", return_value=FakeResult()),
        ):
            resp = self._post(
                _text_payload("wamid.IN1", "Como faço para tirar o visto?")
            )

        self.assertEqual(resp.status_code, 200)
        mock_send.assert_called_once()
        wa_id, body, _cfg = mock_send.call_args[0]
        self.assertEqual(wa_id, WA_ID)
        self.assertIn("Você precisa ir ao consulado.", body)
        self.assertIn("📚 *Fontes:*", body)

    def test_duplicate_message_id_is_processed_once(self):
        payload = _text_payload("wamid.DUPE", "Como faço para tirar o visto?")
        with (
            patch.object(
                processor, "send_text", return_value="wamid.SENT1"
            ) as mock_send,
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch.object(processor, "run_chat_turn", return_value=FakeResult()),
        ):
            self._post(payload)
            self._post(payload)  # Meta retry of the same message id

        self.assertEqual(mock_send.call_count, 1)

    def test_status_only_payload_is_acked_and_ignored(self):
        payload = {
            "entry": [
                {
                    "id": "waba1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                                "statuses": [
                                    {"id": "wamid.OUT1", "status": "delivered"}
                                ],
                            },
                        }
                    ],
                }
            ]
        }
        with patch.object(processor, "run_chat_turn") as mock_run:
            resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        mock_run.assert_not_called()

    def test_oversize_message_is_rejected_without_agent_call(self):
        max_len = load_settings().whatsapp_cloud.max_message_length
        long_text = "a" * (max_len + 1)
        with (
            patch.object(
                processor, "send_text", return_value="wamid.SENT1"
            ) as mock_send,
            patch.object(processor, "run_chat_turn") as mock_run,
        ):
            self._post(_text_payload("wamid.LONG", long_text))

        mock_run.assert_not_called()
        mock_send.assert_called_once()
        self.assertIn("muito longa", mock_send.call_args[0][1])

    def test_rate_limit_throttles_after_default_budget(self):
        limit = load_settings().whatsapp_cloud.rate_limit_per_minute
        with (
            patch.object(
                processor, "send_text", return_value="wamid.SENT1"
            ) as mock_send,
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch.object(processor, "run_chat_turn", return_value=FakeResult()),
        ):
            for i in range(limit):
                self._post(_text_payload(f"wamid.RL{i}", f"pergunta {i}"))
            self._post(_text_payload("wamid.RL-over", "uma a mais"))

        last_call_body = mock_send.call_args_list[-1][0][1]
        self.assertIn("muitas mensagens", last_call_body)

    def test_reset_command_clears_memory_and_confirms_without_agent_call(self):
        with (
            patch.object(
                processor, "send_text", return_value="wamid.SENT1"
            ) as mock_send,
            patch.object(processor, "reset_agent_memory") as mock_reset,
            patch.object(processor, "run_chat_turn") as mock_run,
        ):
            self._post(_text_payload("wamid.RESET1", "/reset"))

        mock_run.assert_not_called()
        mock_reset.assert_called_once()
        self.assertIn("Prontinho", mock_send.call_args[0][1])

    def test_gratitude_after_an_answer_records_feedback_without_agent_call(self):
        with (
            patch.object(processor, "send_text", return_value="wamid.SENT1"),
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch.object(processor, "run_chat_turn", return_value=FakeResult()),
        ):
            self._post(_text_payload("wamid.Q1", "Como faço para tirar o visto?"))

        with (
            patch.object(
                processor, "send_text", return_value="wamid.SENT2"
            ) as mock_send,
            patch.object(processor, "get_feedback_logger") as mock_get_logger,
            patch.object(processor, "run_chat_turn") as mock_run,
        ):
            self._post(_text_payload("wamid.THANKS", "obrigado"))

        mock_run.assert_not_called()
        mock_get_logger.return_value.log_feedback.assert_called_once()
        _, kwargs = mock_get_logger.return_value.log_feedback.call_args
        self.assertEqual(kwargs["message_id"], "wamid.SENT1")
        self.assertEqual(kwargs["rating"], "up")
        self.assertIn("De nada", mock_send.call_args[0][1])

    def test_gratitude_with_no_prior_turn_falls_through_to_agent(self):
        with (
            patch.object(processor, "send_text", return_value="wamid.SENT1"),
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch.object(
                processor, "run_chat_turn", return_value=FakeResult()
            ) as mock_run,
        ):
            self._post(_text_payload("wamid.THANKS-COLD", "obrigado"))

        mock_run.assert_called_once()

    def test_reaction_up_records_feedback_and_sends_ack(self):
        with (
            patch.object(processor, "send_text", return_value="wamid.SENT1"),
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch.object(processor, "run_chat_turn", return_value=FakeResult()),
        ):
            self._post(_text_payload("wamid.Q1", "Como faço para tirar o visto?"))

        with (
            patch.object(processor, "send_text", return_value="wamid.ACK") as mock_send,
            patch.object(processor, "get_feedback_logger") as mock_get_logger,
        ):
            self._post(_reaction_payload("wamid.REACT1", "wamid.SENT1", "👍"))

        mock_get_logger.return_value.log_feedback.assert_called_once()
        _, kwargs = mock_get_logger.return_value.log_feedback.call_args
        self.assertEqual(kwargs["rating"], "up")
        self.assertIn("feedback", mock_send.call_args[0][1].lower())

    def test_reaction_down_records_feedback(self):
        with (
            patch.object(processor, "send_text", return_value="wamid.SENT1"),
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch.object(processor, "run_chat_turn", return_value=FakeResult()),
        ):
            self._post(_text_payload("wamid.Q1", "Como faço para tirar o visto?"))

        with (
            patch.object(processor, "send_text", return_value="wamid.ACK"),
            patch.object(processor, "get_feedback_logger") as mock_get_logger,
        ):
            self._post(_reaction_payload("wamid.REACT2", "wamid.SENT1", "👎"))

        _, kwargs = mock_get_logger.return_value.log_feedback.call_args
        self.assertEqual(kwargs["rating"], "down")

    def test_reaction_on_unknown_message_is_silently_ignored(self):
        with (
            patch.object(processor, "send_text") as mock_send,
            patch.object(processor, "get_feedback_logger") as mock_get_logger,
        ):
            resp = self._post(
                _reaction_payload("wamid.REACT3", "wamid.NEVER-SENT", "👍")
            )

        self.assertEqual(resp.status_code, 200)
        mock_send.assert_not_called()
        mock_get_logger.return_value.log_feedback.assert_not_called()

    def test_bot_disabled_relays_disabled_message_without_agent_call(self):
        cs.set_switch(False, "test", self.db)
        cs._invalidate_enabled_cache()
        with (
            patch.object(
                processor, "send_text", return_value="wamid.SENT1"
            ) as mock_send,
            patch.object(processor, "mark_read_and_typing", return_value=True),
            patch(
                "habitantes.infrastructure.api.routers.chat.run_agent"
            ) as mock_run_agent,
        ):
            self._post(
                _text_payload("wamid.DISABLED1", "Como faço para tirar o visto?")
            )

        mock_run_agent.assert_not_called()
        self.assertIn("indisponível", mock_send.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
