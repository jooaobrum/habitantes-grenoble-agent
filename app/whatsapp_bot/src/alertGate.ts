/**
 * Shadow mirror of `WebhookAlerts.alert()`'s internal gating (Phase 4, A4.1).
 *
 * `antiban/webhooks.ts` is vendored and must stay byte-identical to its
 * upstream source (see its `ATTRIBUTION.md`), so it cannot be changed to
 * expose whether a given `alert()` call actually sent or was gated (below
 * `minRiskLevel`, or inside `cooldownMs`). This module duplicates just the
 * two conditions `WebhookAlerts.alert()` checks — see its lines ~47-55 — as a
 * small pure function, purely so the call site in `index.ts` can log which
 * outcome is *expected*. It is NOT the source of truth for whether a webhook
 * POST happens: the real `WebhookAlerts` instance remains that source of
 * truth, and callers must always invoke the real `alerts.alert()` regardless
 * of what this returns.
 */

/** Same order/semantics as the `riskOrder` array in `antiban/webhooks.ts`. */
const RISK_ORDER = ["low", "medium", "high", "critical"] as const;

export type AlertDecision = "sent" | "skipped_below_min_risk" | "skipped_cooldown";

/**
 * Mirrors `WebhookAlerts.alert()`'s gate: below `minRiskLevel` first, then
 * cooldown. Unknown risk/minRiskLevel strings behave like the vendored code
 * (`indexOf` returns -1, so an unrecognized `risk` is always "below").
 */
export function shouldAlert(
  risk: string,
  minRiskLevel: string,
  msSinceLastAlert: number,
  cooldownMs: number,
): AlertDecision {
  if (RISK_ORDER.indexOf(risk as (typeof RISK_ORDER)[number]) <
    RISK_ORDER.indexOf(minRiskLevel as (typeof RISK_ORDER)[number])) {
    return "skipped_below_min_risk";
  }
  if (msSinceLastAlert < cooldownMs) {
    return "skipped_cooldown";
  }
  return "sent";
}
