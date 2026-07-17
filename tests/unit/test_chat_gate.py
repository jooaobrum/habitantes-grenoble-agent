import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from habitantes.infrastructure import control_store as cs
from habitantes.infrastructure.api.main import app

_CHAT_BODY = {"chat_id": "c1", "message": "Olá", "message_id": "m1"}


class TestChatGate(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.db = Path(self._tmp.name) / "control.db"
        cs.init_db(self.db)
        # is_enabled() reads the module-global DEFAULT_DB_PATH at call time.
        self._patcher = patch.object(cs, "DEFAULT_DB_PATH", self.db)
        self._patcher.start()
        cs._invalidate_enabled_cache()
        self.client = TestClient(app)

    def tearDown(self):
        self._patcher.stop()
        cs._invalidate_enabled_cache()
        self._tmp.cleanup()

    def test_disabled_returns_structured_response_without_agent(self):
        cs.set_switch(False, "admin", self.db)
        cs._invalidate_enabled_cache()

        with patch("habitantes.infrastructure.api.routers.chat.run_agent") as mock_run:
            resp = self.client.post("/chat/", json=_CHAT_BODY)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["error_code"], "BOT_DISABLED")
        self.assertTrue(body["retryable"])
        self.assertIn("message", body)
        mock_run.assert_not_called()

    def test_reenabling_restores_normal_chat(self):
        cs.set_switch(True, "admin", self.db)
        cs._invalidate_enabled_cache()

        fake_state = {
            "answer": "Bonjour",
            "sources": [],
            "intent": "qa",
            "category": "visa",
            "confidence": 0.9,
            "cached": False,
        }
        with patch(
            "habitantes.infrastructure.api.routers.chat.run_agent",
            return_value=fake_state,
        ) as mock_run:
            resp = self.client.post("/chat/", json=_CHAT_BODY)

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["answer"], "Bonjour")
        self.assertNotIn("error_code", body)
        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
