import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from habitantes.infrastructure import control_store as cs
from habitantes.infrastructure.api.main import app
from habitantes.infrastructure.api.routers.admin import get_control_db_path

TOKEN = "test-admin-token"  # set by tests/conftest.py
AUTH = {"X-Admin-Token": TOKEN}
_CHAT_BODY = {"chat_id": "c1", "message": "Olá", "message_id": "m1"}


class TestFailOpen(unittest.TestCase):
    """T14: a corrupt/unreadable control store must never take the chat path
    down with it, and its own failure must be visible in /admin/status."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.db = Path(self._tmp.name) / "control.db"
        # Corrupt: any sqlite3 read against this file raises DatabaseError.
        self.db.write_bytes(b"this is not a valid sqlite database file")

        self._patcher = patch.object(cs, "DEFAULT_DB_PATH", self.db)
        self._patcher.start()
        cs._invalidate_enabled_cache()
        app.dependency_overrides[get_control_db_path] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self._patcher.stop()
        cs._invalidate_enabled_cache()
        self._tmp.cleanup()

    def test_chat_still_answers_when_control_store_is_corrupt(self):
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

    def test_admin_status_reports_control_store_critical(self):
        resp = self.client.get("/admin/status", headers=AUTH)

        self.assertEqual(resp.status_code, 200)
        services = {s["name"]: s["status"] for s in resp.json()["services"]}
        self.assertEqual(services.get("control_store"), "critical")


if __name__ == "__main__":
    unittest.main()
