import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { HealthMonitor } from "./health.js";

const BASE = new Date("2026-01-01T00:00:00Z").getTime();

describe("HealthMonitor", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("raises risk to 'high' on a single 403 (forbidden) signal", () => {
    const monitor = new HealthMonitor();
    monitor.recordDisconnect("403");
    const status = monitor.getStatus();
    expect(status.risk).toBe("high");
    expect(status.stats.forbiddenErrors).toBe(1);
  });

  it("raises risk to 'high' on a single 401 (loggedOut) signal", () => {
    const monitor = new HealthMonitor();
    monitor.recordDisconnect("401");
    expect(monitor.getStatus().risk).toBe("high");
  });

  it("raises risk to 'critical' when 403 and loggedOut combine", () => {
    const monitor = new HealthMonitor();
    monitor.recordDisconnect("403");
    monitor.recordDisconnect("loggedOut");
    expect(monitor.getStatus().risk).toBe("critical");
  });

  it("raises risk to 'medium' on a 463 reachout-timelock signal", () => {
    const monitor = new HealthMonitor();
    monitor.recordReachoutTimelock("463");
    expect(monitor.getStatus().risk).toBe("medium");
  });

  it("maps the disconnect-warning threshold and the critical threshold to distinct reasons", () => {
    const warn = new HealthMonitor({ disconnectWarningThreshold: 3, disconnectCriticalThreshold: 10 });
    for (let i = 0; i < 3; i++) warn.recordDisconnect("network-blip");
    const warnStatus = warn.getStatus();
    expect(warnStatus.stats.disconnectsLastHour).toBe(3);
    expect(warnStatus.reasons.some((r) => r.includes("critical threshold"))).toBe(false);

    const crit = new HealthMonitor({ disconnectWarningThreshold: 3, disconnectCriticalThreshold: 5 });
    for (let i = 0; i < 5; i++) crit.recordDisconnect("network-blip");
    const critStatus = crit.getStatus();
    expect(critStatus.reasons.some((r) => r.includes("critical threshold"))).toBe(true);
  });

  it("decays the risk score back down over time", () => {
    const monitor = new HealthMonitor();
    monitor.recordDisconnect("403"); // score 40 (severe → 2 pts/min decay)
    expect(monitor.getStatus().risk).toBe("high");

    vi.setSystemTime(BASE + 10 * 60_000); // +10 min → 40 - 20 = 20
    expect(monitor.getStatus().risk).toBe("medium");

    vi.setSystemTime(BASE + 25 * 60_000); // fully decayed
    const decayed = monitor.getStatus();
    expect(decayed.risk).toBe("low");
    expect(decayed.score).toBe(0);
  });

  it("fires onRiskChange only on an actual level transition, not on every score update", () => {
    const onRiskChange = vi.fn();
    // Set the failed-message threshold very high so recordMessageFailed below doesn't
    // itself add score — isolating the "no transition → no callback" behaviour.
    const monitor = new HealthMonitor({ onRiskChange, failedMessageThreshold: 1000 });

    monitor.recordDisconnect("403"); // low -> high: transition, fires
    expect(onRiskChange).toHaveBeenCalledTimes(1);
    expect(onRiskChange.mock.calls[0][0].risk).toBe("high");

    monitor.recordMessageFailed();
    monitor.recordMessageFailed();
    expect(onRiskChange).toHaveBeenCalledTimes(1); // still 'high' — no fire

    // Let the score fully decay to 'low', then trigger a recompute via another event.
    vi.setSystemTime(BASE + 60 * 60_000);
    monitor.recordMessageFailed();
    expect(onRiskChange).toHaveBeenCalledTimes(2);
    expect(onRiskChange.mock.calls[1][0].risk).toBe("low");
  });
});
