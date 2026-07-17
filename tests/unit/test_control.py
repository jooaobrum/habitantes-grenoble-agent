import unittest

from habitantes.domain.control import (
    BreachResult,
    ThresholdsSnapshot,
    evaluate_thresholds,
)


def _thresholds(**overrides) -> ThresholdsSnapshot:
    base = dict(
        daily_cost_limit_usd=5.0,
        health_grace_checks=3,
        auto_disable_enabled=True,
    )
    base.update(overrides)
    return ThresholdsSnapshot(**base)


class TestEvaluateThresholds(unittest.TestCase):
    def test_under_both_limits_returns_none(self):
        result = evaluate_thresholds(
            cost_today_usd=2.0,
            service_streaks={"qdrant": 0, "openai": 1},
            thresholds=_thresholds(),
        )
        self.assertIsNone(result)

    def test_cost_over_limit_returns_cost_breach(self):
        result = evaluate_thresholds(
            cost_today_usd=5.12,
            service_streaks={"qdrant": 0, "openai": 0},
            thresholds=_thresholds(),
        )
        self.assertIsInstance(result, BreachResult)
        self.assertEqual(result.trigger, "daily_cost_limit_breach")
        self.assertEqual(result.changed_by, "watchdog:daily_cost_limit")
        self.assertIsNone(result.service)
        self.assertIn("5.12", result.measured)

    def test_service_streak_at_grace_returns_health_breach_naming_service(self):
        result = evaluate_thresholds(
            cost_today_usd=0.0,
            service_streaks={"qdrant": 0, "openai": 3},
            thresholds=_thresholds(),
        )
        self.assertIsInstance(result, BreachResult)
        self.assertEqual(result.service, "openai")
        self.assertEqual(result.trigger, "health:openai")
        self.assertEqual(result.changed_by, "watchdog:health:openai")
        self.assertIn("3/3", result.measured)

    def test_cost_checked_before_health(self):
        # Both breach; cost wins because it is checked first.
        result = evaluate_thresholds(
            cost_today_usd=10.0,
            service_streaks={"openai": 5},
            thresholds=_thresholds(),
        )
        self.assertEqual(result.trigger, "daily_cost_limit_breach")

    def test_auto_disable_disabled_still_returns_breach(self):
        # Evaluation is not action: the breach is returned regardless of the flag.
        result = evaluate_thresholds(
            cost_today_usd=6.0,
            service_streaks={},
            thresholds=_thresholds(auto_disable_enabled=False),
        )
        self.assertIsInstance(result, BreachResult)
        self.assertEqual(result.trigger, "daily_cost_limit_breach")


if __name__ == "__main__":
    unittest.main()
