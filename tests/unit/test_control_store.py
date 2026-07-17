import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from habitantes.infrastructure import control_store as cs


class TestControlStore(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.db = Path(self._tmp.name) / "control.db"
        cs.init_db(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_switch(self):
        switch = cs.get_switch(self.db)
        self.assertTrue(switch["enabled"])
        self.assertEqual(switch["changed_by"], "default")
        self.assertIsNotNone(switch["changed_at"])

    def test_default_thresholds(self):
        thresholds = cs.get_thresholds(self.db)
        # Defaults come from settings.alerts.
        self.assertEqual(thresholds["daily_cost_limit_usd"], 5.0)
        self.assertEqual(thresholds["health_grace_checks"], 3)
        self.assertTrue(thresholds["auto_disable_enabled"])

    def test_init_is_idempotent(self):
        cs.set_switch(False, "admin", self.db)
        cs.init_db(self.db)  # must not reset the existing singleton row
        self.assertFalse(cs.get_switch(self.db)["enabled"])

    def test_transition_switch_state(self):
        updated = cs.set_switch(False, "watchdog:daily_cost_limit", self.db)
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["changed_by"], "watchdog:daily_cost_limit")
        self.assertFalse(cs.get_switch(self.db)["enabled"])

    def test_set_thresholds(self):
        updated = cs.set_thresholds(
            daily_cost_limit_usd=10.0,
            health_grace_checks=5,
            email_to="ops@example.com",
            auto_disable_enabled=False,
            monthly_budget_usd=200.0,
            db_path=self.db,
        )
        self.assertEqual(updated["daily_cost_limit_usd"], 10.0)
        self.assertEqual(updated["health_grace_checks"], 5)
        self.assertEqual(updated["email_to"], "ops@example.com")
        self.assertFalse(updated["auto_disable_enabled"])
        self.assertEqual(updated["monthly_budget_usd"], 200.0)

    def test_append_and_resolve_alerts(self):
        first = cs.append_alert(
            trigger="daily_cost_limit_breach",
            measured="$5.12 of $5.00",
            action="switch_disabled",
            email_sent=True,
            db_path=self.db,
        )
        second = cs.append_alert(
            trigger="health:openai",
            measured="3/3 failed checks",
            action="switch_disabled",
            email_sent=False,
            db_path=self.db,
        )
        self.assertNotEqual(first, second)

        alerts = cs.read_alerts(db_path=self.db)
        self.assertEqual(len(alerts), 2)
        self.assertTrue(all(a["status"] == "active" for a in alerts))

        resolved = cs.resolve_open_alerts(self.db)
        self.assertEqual(resolved, 2)
        alerts = cs.read_alerts(db_path=self.db)
        self.assertTrue(all(a["status"] == "resolved" for a in alerts))
        self.assertTrue(all(a["resolved_at"] is not None for a in alerts))

    def test_health_snapshot_upsert_and_read_consecutive_failures(self):
        cs.write_health_snapshot(
            service="openai",
            status="unreachable",
            latency_ms=None,
            consecutive_failures=1,
            detail="timeout",
            db_path=self.db,
        )
        # Upsert same service: overwrites the row, bumps the streak.
        cs.write_health_snapshot(
            service="openai",
            status="unreachable",
            latency_ms=None,
            consecutive_failures=2,
            detail="timeout",
            db_path=self.db,
        )
        snapshot = cs.read_health_snapshot(self.db)
        self.assertEqual(len(snapshot), 1)
        row = snapshot[0]
        self.assertEqual(row["service"], "openai")
        self.assertEqual(row["consecutive_failures"], 2)
        self.assertEqual(row["status"], "unreachable")

    def test_heartbeat(self):
        self.assertIsNone(cs.read_heartbeat("telegram_bot", self.db))
        cs.touch_heartbeat("telegram_bot", self.db)
        hb = cs.read_heartbeat("telegram_bot", self.db)
        self.assertIsNotNone(hb)
        self.assertEqual(hb["service"], "telegram_bot")
        self.assertIsNotNone(hb["last_seen_at"])


if __name__ == "__main__":
    unittest.main()
