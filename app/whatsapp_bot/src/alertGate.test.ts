import { describe, it, expect } from "vitest";

import { shouldAlert } from "./alertGate.js";

describe("shouldAlert", () => {
  it("sends when risk meets the minimum and cooldown has elapsed", () => {
    expect(shouldAlert("high", "medium", 999_999, 300_000)).toBe("sent");
    expect(shouldAlert("medium", "medium", 999_999, 300_000)).toBe("sent");
  });

  it("skips when risk is below minRiskLevel, regardless of cooldown", () => {
    expect(shouldAlert("low", "medium", 999_999, 300_000)).toBe(
      "skipped_below_min_risk",
    );
    // Even with no prior alert at all (msSinceLastAlert huge), risk still gates first.
    expect(shouldAlert("low", "high", Number.MAX_SAFE_INTEGER, 300_000)).toBe(
      "skipped_below_min_risk",
    );
  });

  it("skips when inside the cooldown window, even if risk qualifies", () => {
    expect(shouldAlert("critical", "medium", 1_000, 300_000)).toBe(
      "skipped_cooldown",
    );
  });

  it("risk check takes precedence over cooldown check (mirrors webhooks.ts order)", () => {
    // Below minRiskLevel AND inside cooldown — must report the risk reason.
    expect(shouldAlert("low", "medium", 1_000, 300_000)).toBe(
      "skipped_below_min_risk",
    );
  });

  it("treats an unrecognized risk/minRiskLevel like the vendored indexOf(-1) behaviour", () => {
    expect(shouldAlert("unknown", "medium", 999_999, 300_000)).toBe(
      "skipped_below_min_risk",
    );
  });

  it("never blocks the first-ever alert (lastAlertTime = 0 semantics)", () => {
    // Mirrors WebhookAlerts starting with `lastAlertTime = 0`, so a huge
    // "time since" on the very first evaluation always clears cooldown.
    expect(shouldAlert("critical", "critical", Date.now(), 300_000)).toBe(
      "sent",
    );
  });
});
