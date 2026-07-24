import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { WarmUp } from "./warmup.js";

const BASE = new Date("2026-01-01T00:00:00Z").getTime();

describe("WarmUp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("canSend() stays true across normal volume under a high floor (inertness)", () => {
    // day1Limit modelling the app's "floor" — well above ordinary community volume.
    const warmup = new WarmUp({ day1Limit: 200, warmUpDays: 7, growthFactor: 1.5 });

    for (let i = 0; i < 50; i++) {
      expect(warmup.canSend()).toBe(true);
      warmup.record();
    }
    expect(warmup.canSend()).toBe(true);
  });

  it("flips canSend() to false once an over-floor burst exceeds the daily limit", () => {
    const warmup = new WarmUp({ day1Limit: 5, warmUpDays: 7, growthFactor: 1.5 });

    for (let i = 0; i < 5; i++) {
      expect(warmup.canSend()).toBe(true);
      warmup.record();
    }
    // 6th message of the day exceeds the day1Limit floor.
    expect(warmup.canSend()).toBe(false);
  });

  it("re-engages warm-up after inactivity beyond the configured threshold", () => {
    const warmup = new WarmUp({
      day1Limit: 5,
      warmUpDays: 1,
      growthFactor: 1.5,
      inactivityThresholdHours: 72,
    });

    warmup.record();
    expect(warmup.getStatus().phase).toBe("warming");

    // Advance past warmUpDays so the module graduates.
    vi.setSystemTime(BASE + 2 * 86_400_000);
    expect(warmup.canSend()).toBe(true);
    expect(warmup.getStatus().phase).toBe("graduated");

    // Advance well beyond the inactivity threshold with no further activity.
    vi.setSystemTime(BASE + 2 * 86_400_000 + 73 * 3_600_000);
    expect(warmup.canSend()).toBe(true); // fresh warm-up budget, not a stale graduated state
    expect(warmup.getStatus().phase).toBe("warming"); // re-engaged
  });

  it("round-trips state through exportState()/importState()", () => {
    const original = new WarmUp({ day1Limit: 50, warmUpDays: 7, growthFactor: 1.5 });
    original.record();
    original.record();
    original.record();

    const exported = original.exportState();

    const restored = new WarmUp({ day1Limit: 50, warmUpDays: 7, growthFactor: 1.5 });
    restored.importState(exported);

    expect(restored.getStatus().todaySent).toBe(original.getStatus().todaySent);
    expect(restored.getStatus().day).toBe(original.getStatus().day);
    expect(restored.getStatus().phase).toBe(original.getStatus().phase);
  });
});
