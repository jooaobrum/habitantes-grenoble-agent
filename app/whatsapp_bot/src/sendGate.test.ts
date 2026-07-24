import { describe, it, expect, vi } from "vitest";
import pino from "pino";

import { HealthMonitor } from "./antiban/health.js";
import { RateLimiter as AccountRateLimiter } from "./antiban/rateLimiter.js";
import { WarmUp } from "./antiban/warmup.js";
import { SendGate } from "./sendGate.js";

/** Silent logger — we assert behaviour, not log output. */
const silentLogger = pino({ enabled: false });

/** A fake Baileys socket: just the `sendMessage` surface the gate calls. */
function fakeSocket() {
  return { sendMessage: vi.fn(async (_jid: string, _content: unknown) => ({ key: { id: "wamid-1" } })) };
}

/** Permissive real instances — normal sends should sail through unblocked. */
function permissiveDeps(overrides: Partial<{ warmup: WarmUp | undefined; hardPauseEnabled: boolean }> = {}) {
  const rateLimiter = new AccountRateLimiter({
    maxPerMinute: 1000,
    maxPerHour: 1000,
    maxPerDay: 1000,
    minDelayMs: 0,
    maxDelayMs: 0,
  });
  const health = new HealthMonitor({ autoPauseAt: "critical" });
  const warmup =
    overrides.warmup === undefined && !("warmup" in overrides)
      ? new WarmUp({ day1Limit: 1000, warmUpDays: 7 })
      : overrides.warmup;
  return {
    rateLimiter,
    health,
    warmup,
    hardPauseEnabled: overrides.hardPauseEnabled ?? false,
    logger: silentLogger,
    sleepFn: vi.fn(async () => undefined),
  };
}

describe("SendGate", () => {
  it("sends normally: awaits the computed delay, calls sendMessage, records on rateLimiter and warmup", async () => {
    const sock = fakeSocket();
    const deps = permissiveDeps();
    const gate = new SendGate(deps);

    const recordSpy = vi.spyOn(deps.rateLimiter, "record");
    const warmupRecordSpy = vi.spyOn(deps.warmup!, "record");

    const result = await gate.send(sock as never, "user@s.whatsapp.net", "hello");

    expect(sock.sendMessage).toHaveBeenCalledWith("user@s.whatsapp.net", { text: "hello" });
    expect(deps.sleepFn).toHaveBeenCalled();
    expect(recordSpy).toHaveBeenCalledWith("user@s.whatsapp.net", "hello");
    expect(warmupRecordSpy).toHaveBeenCalled();
    expect(result).toEqual({ key: { id: "wamid-1" } });
  });

  it("returns undefined and skips sendMessage when WarmUp.canSend() is false", async () => {
    const sock = fakeSocket();
    const warmup = new WarmUp({ day1Limit: 1, warmUpDays: 7 });
    // Exhaust the day-1 floor of 1.
    warmup.record();
    const deps = permissiveDeps({ warmup });
    const gate = new SendGate(deps);

    const result = await gate.send(sock as never, "user@s.whatsapp.net", "hello");

    expect(result).toBeUndefined();
    expect(sock.sendMessage).not.toHaveBeenCalled();
  });

  it("defers (no send) when hard-pause is enabled and health.isPaused() is true", async () => {
    const sock = fakeSocket();
    const deps = permissiveDeps({ hardPauseEnabled: true });
    // Force risk to critical so isPaused() (autoPauseAt: 'critical') returns true.
    deps.health.recordDisconnect("403");
    deps.health.recordDisconnect("403");

    const gate = new SendGate(deps);
    const result = await gate.send(sock as never, "user@s.whatsapp.net", "hello");

    expect(result).toBeUndefined();
    expect(sock.sendMessage).not.toHaveBeenCalled();
  });

  it("does NOT defer on health.isPaused() when hard-pause is disabled (default)", async () => {
    const sock = fakeSocket();
    const deps = permissiveDeps({ hardPauseEnabled: false });
    // Same forced-critical state as above, but the flag is off this time.
    deps.health.recordDisconnect("403");
    deps.health.recordDisconnect("403");
    expect(deps.health.isPaused()).toBe(true); // sanity: the module itself would block

    const gate = new SendGate(deps);
    const result = await gate.send(sock as never, "user@s.whatsapp.net", "hello");

    expect(result).toEqual({ key: { id: "wamid-1" } });
    expect(sock.sendMessage).toHaveBeenCalledTimes(1);
  });

  it("defers when the account RateLimiter returns -1 (hard block)", async () => {
    const sock = fakeSocket();
    const rateLimiter = new AccountRateLimiter({ maxPerDay: 1, maxPerHour: 1000, maxPerMinute: 1000 });
    // Exhaust the daily cap of 1 directly against the limiter.
    await rateLimiter.getDelay("user@s.whatsapp.net", "m1");
    rateLimiter.record("user@s.whatsapp.net", "m1");

    const deps = { ...permissiveDeps(), rateLimiter };
    const gate = new SendGate(deps);

    const result = await gate.send(sock as never, "user@s.whatsapp.net", "m2");

    expect(result).toBeUndefined();
    expect(sock.sendMessage).not.toHaveBeenCalled();
  });

  it("routes gates in order: warm-up block takes effect before the socket is ever touched", async () => {
    const sock = fakeSocket();
    const warmup = new WarmUp({ day1Limit: 1, warmUpDays: 7 });
    warmup.record();
    const deps = permissiveDeps({ warmup, hardPauseEnabled: true });
    // Also force critical, so warm-up (checked first) is what we're isolating.
    deps.health.recordDisconnect("403");
    deps.health.recordDisconnect("403");

    const gate = new SendGate(deps);
    await gate.send(sock as never, "user@s.whatsapp.net", "hello");

    expect(sock.sendMessage).not.toHaveBeenCalled();
  });

  it("on a sendMessage throw, calls health.recordMessageFailed and rethrows", async () => {
    const sock = { sendMessage: vi.fn(async () => { throw new Error("boom"); }) };
    const deps = permissiveDeps();
    const recordFailedSpy = vi.spyOn(deps.health, "recordMessageFailed");
    const gate = new SendGate(deps);

    await expect(gate.send(sock as never, "user@s.whatsapp.net", "hello")).rejects.toThrow("boom");
    expect(recordFailedSpy).toHaveBeenCalledWith("boom");
  });

  it("does not blow up when constructed without a warmup instance (warmup.enabled=false)", async () => {
    const sock = fakeSocket();
    const deps = permissiveDeps({ warmup: undefined });
    const gate = new SendGate(deps);

    const result = await gate.send(sock as never, "user@s.whatsapp.net", "hello");

    expect(result).toEqual({ key: { id: "wamid-1" } });
    expect(sock.sendMessage).toHaveBeenCalledTimes(1);
  });
});
