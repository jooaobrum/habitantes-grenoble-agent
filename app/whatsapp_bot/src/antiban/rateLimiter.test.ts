import { describe, it, expect } from "vitest";
import { RateLimiter } from "./rateLimiter.js";

describe("RateLimiter", () => {
  it("hard-blocks (-1) once the daily cap is exceeded", async () => {
    const limiter = new RateLimiter({ maxPerDay: 2, maxPerHour: 1000, maxPerMinute: 1000 });

    await limiter.getDelay("a", "m1");
    limiter.record("a", "m1");
    await limiter.getDelay("a", "m2");
    limiter.record("a", "m2");

    const delay = await limiter.getDelay("a", "m3");
    expect(delay).toBe(-1);
  });

  it("returns a defer delay (not a hard block) once the hourly cap is exceeded", async () => {
    const limiter = new RateLimiter({ maxPerHour: 2, maxPerDay: 1000, maxPerMinute: 1000 });

    await limiter.getDelay("a", "m1");
    limiter.record("a", "m1");
    await limiter.getDelay("a", "m2");
    limiter.record("a", "m2");

    const delay = await limiter.getDelay("a", "m3");
    expect(delay).toBeGreaterThanOrEqual(60_000);
  });

  it("returns a defer delay once the per-minute cap is exceeded", async () => {
    const limiter = new RateLimiter({ maxPerMinute: 2, maxPerHour: 1000, maxPerDay: 1000 });

    await limiter.getDelay("a", "m1");
    limiter.record("a", "m1");
    await limiter.getDelay("a", "m2");
    limiter.record("a", "m2");

    const delay = await limiter.getDelay("a", "m3");
    expect(delay).toBeGreaterThanOrEqual(1_000);
  });

  it("returns a bounded, jittered delay under normal volume — not a fixed constant", async () => {
    const limiter = new RateLimiter({
      maxPerMinute: 1000,
      maxPerHour: 1000,
      maxPerDay: 1000,
      minDelayMs: 1000,
      maxDelayMs: 2000,
      newChatDelayMs: 0,
      burstAllowance: 0,
    });

    const delays = new Set<number>();
    for (let i = 0; i < 8; i++) {
      const d = await limiter.getDelay("a", `msg-${i}`);
      limiter.record("a", `msg-${i}`);
      expect(d).toBeGreaterThan(0);
      expect(d).toBeLessThan(10_000); // bounded — no runaway value
      delays.add(d);
    }

    // Jittered: repeated calls under identical caps should not all collapse to one value.
    expect(delays.size).toBeGreaterThan(1);
  });

  it("adaptLimits scales the effective caps down and the pacing delay up", async () => {
    const limiter = new RateLimiter({
      maxPerMinute: 100,
      maxPerHour: 1000,
      maxPerDay: 1000,
      minDelayMs: 1000,
      maxDelayMs: 1000,
      newChatDelayMs: 0,
      burstAllowance: 0,
    });

    const before = await limiter.getDelay("a", "");
    limiter.record("a", "");
    expect(before).toBe(1000);

    limiter.adaptLimits(0.1);
    expect(limiter.getStats().limits.perMinute).toBe(10); // floor(100 * 0.1)
    expect(limiter.getCurrentFactor()).toBeCloseTo(0.1);

    const after = await limiter.getDelay("a", "");
    expect(after).toBeGreaterThan(before);
  });

  it("record() advances the window so a subsequent getDelay reflects the recorded send", async () => {
    const limiter = new RateLimiter({ maxPerMinute: 1, maxPerHour: 1000, maxPerDay: 1000 });

    const first = await limiter.getDelay("a", "m1");
    expect(first).toBeGreaterThanOrEqual(0);
    expect(first).toBeLessThan(60_000); // not yet at cap

    limiter.record("a", "m1");

    // The window now holds the recorded message, so the per-minute cap (1) is reached.
    const second = await limiter.getDelay("a", "m2");
    expect(second).toBeGreaterThanOrEqual(1_000);
  });
});
