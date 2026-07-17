import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from habitantes.infrastructure import control_store as cs
from habitantes.infrastructure.api.main import app
from habitantes.infrastructure.api.routers.admin import get_control_db_path

TOKEN = "test-admin-token"  # set by tests/conftest.py
AUTH = {"X-Admin-Token": TOKEN}


class TestAdminRouter(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.db = Path(self._tmp.name) / "control.db"
        cs.init_db(self.db)
        app.dependency_overrides[get_control_db_path] = lambda: self.db
        # TestClient without a `with` block does not fire startup events, so the
        # watchdog task and real-path init_db never run.
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self._tmp.cleanup()

    # ── Auth ─────────────────────────────────────────────────────────────────

    def test_missing_token_is_401_no_state_change(self):
        resp = self.client.post("/admin/switch", json={"enabled": False})
        self.assertEqual(resp.status_code, 401)
        self.assertTrue(cs.get_switch(self.db)["enabled"])  # unchanged

    def test_wrong_token_is_401_no_state_change(self):
        resp = self.client.post(
            "/admin/switch",
            json={"enabled": False},
            headers={"X-Admin-Token": "wrong"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertTrue(cs.get_switch(self.db)["enabled"])

    def test_status_requires_token(self):
        self.assertEqual(self.client.get("/admin/status").status_code, 401)

    # ── Read path ────────────────────────────────────────────────────────────

    def test_status_full_read_path(self):
        cs.write_health_snapshot("qdrant", "ok", 12.0, 0, None, self.db)
        cs.append_alert(
            "test_alert", None, "test_email_sent", True, "resolved", self.db
        )

        resp = self.client.get("/admin/status", headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("switch", body)
        self.assertIn("services", body)
        self.assertIn("kpis", body)
        self.assertIn("thresholds", body)
        self.assertIn("alerts", body)
        self.assertTrue(body["switch"]["enabled"])
        self.assertEqual(body["services"][0]["name"], "qdrant")
        self.assertEqual(body["thresholds"]["daily_cost_limit_usd"], 5.0)
        self.assertEqual(len(body["alerts"]), 1)

    # ── Switch ───────────────────────────────────────────────────────────────

    def test_switch_off_appends_active_alert(self):
        resp = self.client.post("/admin/switch", json={"enabled": False}, headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["enabled"])
        self.assertFalse(cs.get_switch(self.db)["enabled"])
        alerts = cs.read_alerts(db_path=self.db)
        self.assertEqual(alerts[0]["trigger"], "manual:switch_off")
        self.assertEqual(alerts[0]["status"], "active")

    def test_switch_on_resolves_open_alerts(self):
        cs.set_switch(False, "watchdog:daily_cost_limit", self.db)
        cs.append_alert(
            "daily_cost_limit_breach",
            "$6 of $5",
            "switch_disabled",
            True,
            "active",
            self.db,
        )

        resp = self.client.post("/admin/switch", json={"enabled": True}, headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(cs.get_switch(self.db)["enabled"])
        alerts = cs.read_alerts(db_path=self.db)
        self.assertTrue(all(a["status"] == "resolved" for a in alerts))

    # ── Thresholds ───────────────────────────────────────────────────────────

    def test_thresholds_write_preserves_monthly_budget(self):
        resp = self.client.post(
            "/admin/thresholds",
            json={
                "daily_cost_limit_usd": 12.0,
                "health_grace_checks": 4,
                "email_to": "ops@example.com",
                "auto_disable_enabled": False,
            },
            headers=AUTH,
        )
        self.assertEqual(resp.status_code, 200)
        stored = cs.get_thresholds(self.db)
        self.assertEqual(stored["daily_cost_limit_usd"], 12.0)
        self.assertEqual(stored["health_grace_checks"], 4)
        self.assertEqual(stored["email_to"], "ops@example.com")
        self.assertFalse(stored["auto_disable_enabled"])
        # monthly_budget is display-only — untouched from the seeded default.
        self.assertEqual(stored["monthly_budget_usd"], 120.0)

    def test_thresholds_invalid_is_422_no_persist(self):
        resp = self.client.post(
            "/admin/thresholds",
            json={
                "daily_cost_limit_usd": -5.0,
                "health_grace_checks": 3,
                "email_to": "ops@example.com",
                "auto_disable_enabled": True,
            },
            headers=AUTH,
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(cs.get_thresholds(self.db)["daily_cost_limit_usd"], 5.0)

    # ── Heartbeat ────────────────────────────────────────────────────────────

    def test_heartbeat_touches_store(self):
        self.assertIsNone(cs.read_heartbeat("telegram_bot", self.db))
        resp = self.client.post(
            "/admin/heartbeat", json={"service": "telegram_bot"}, headers=AUTH
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(cs.read_heartbeat("telegram_bot", self.db))

    # ── Test alert ───────────────────────────────────────────────────────────

    def test_test_alert_logs_resolved_row(self):
        resp = self.client.post("/admin/test-alert", headers=AUTH)
        self.assertEqual(resp.status_code, 200)
        # No SMTP configured in tests → email_sent False, but a row is still logged.
        self.assertFalse(resp.json()["email_sent"])
        alerts = cs.read_alerts(db_path=self.db)
        self.assertEqual(alerts[0]["trigger"], "test_alert")
        self.assertEqual(alerts[0]["status"], "resolved")
        # Switch is never touched by a test alert.
        self.assertTrue(cs.get_switch(self.db)["enabled"])


if __name__ == "__main__":
    unittest.main()
