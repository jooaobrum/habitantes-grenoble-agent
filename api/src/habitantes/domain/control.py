"""Pure threshold-evaluation logic for the Control Center.

No I/O, no settings, no SQLite: this module receives everything it needs as
arguments so it stays unit-testable with plain values. The decision of whether
to *act* on a breach (disable the switch, send an email) lives in the watchdog,
not here — evaluation is not action.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdsSnapshot:
    """The subset of persisted thresholds that threshold evaluation reads."""

    daily_cost_limit_usd: float
    health_grace_checks: int
    auto_disable_enabled: bool = True
    email_to: str = ""
    monthly_budget_usd: float = 0.0


@dataclass(frozen=True)
class BreachResult:
    """A single detected breach. `service` is set only for health breaches."""

    trigger: str  # alert_log trigger, e.g. "daily_cost_limit_breach" | "health:openai"
    changed_by: str  # switch changed_by, e.g. "watchdog:daily_cost_limit"
    measured: str  # human-readable, e.g. "$5.12 of $5.00" | "3/3 failed checks"
    service: str | None = None


def evaluate_thresholds(
    cost_today_usd: float,
    service_streaks: dict[str, int],
    thresholds: ThresholdsSnapshot,
) -> BreachResult | None:
    """Return the first breach found, or None if all limits are respected.

    Cost is checked before health: a cost breach is the more common and more
    urgent case for a community bot. `auto_disable_enabled` is intentionally
    ignored here — the caller decides whether to act on the returned breach.
    """
    if cost_today_usd >= thresholds.daily_cost_limit_usd:
        return BreachResult(
            trigger="daily_cost_limit_breach",
            changed_by="watchdog:daily_cost_limit",
            measured=f"${cost_today_usd:.2f} of ${thresholds.daily_cost_limit_usd:.2f}",
        )

    for service, streak in service_streaks.items():
        if streak >= thresholds.health_grace_checks:
            return BreachResult(
                trigger=f"health:{service}",
                changed_by=f"watchdog:health:{service}",
                measured=f"{streak}/{thresholds.health_grace_checks} failed checks",
                service=service,
            )

    return None
