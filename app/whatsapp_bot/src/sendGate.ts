/**
 * The guarded outbound send path (Phase 2, A2.1).
 *
 * Consolidates every WhatsApp send behind one seam, in order:
 *   WarmUp.canSend → Health pause gate → account-wide RateLimiter delay →
 *   sock.sendMessage
 *
 * `SendGate` is constructed once and owned by `index.ts` (process-lived, like
 * `deps.rateLimiter` / `deps.dedup` / `deps.locks`), so it survives socket
 * reconnects. It deliberately does NOT hold a socket reference — the socket is
 * recreated on every reconnect (see `connection.ts`), so callers pass the
 * *current* socket into `send()` on every call, mirroring how `handlers.ts`'s
 * `safeSend(sock, jid, text, logger)` already works today.
 */
import type { WASocket } from "@whiskeysockets/baileys";
import type { Logger } from "pino";

import type { HealthMonitor } from "./antiban/health.js";
import type { RateLimiter as AccountRateLimiter } from "./antiban/rateLimiter.js";
import type { WarmUp } from "./antiban/warmup.js";

/** Minimal shape of a Baileys `sendMessage` result we rely on (`key.id`). */
export interface SendGateResult {
  key?: { id?: string };
  [k: string]: unknown;
}

export interface SendGateDeps {
  /** Account-wide (vendored) rate limiter — "is the number as a whole too fast?" */
  rateLimiter: AccountRateLimiter;
  health: HealthMonitor;
  /** Present only when `whatsapp.antiban.warmup.enabled` is true; absent = always-allowed. */
  warmup?: WarmUp;
  /**
   * Mirrors `whatsapp.antiban.health.hard_pause_enabled`. `HealthMonitor.isPaused()`
   * has no "disabled" concept of its own — the caller (this gate) enforces the
   * flag: `health.isPaused()` is only consulted when this is `true`.
   */
  hardPauseEnabled: boolean;
  logger: Logger;
  /** Injectable for fake-clock tests; defaults to a real `setTimeout`-based sleep. */
  sleepFn?: (ms: number) => Promise<void>;
}

function realSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * The single guarded outbound path. See design.md "The guarded send path
 * (`sendGate.ts`)" for the authoritative behaviour this implements.
 */
export class SendGate {
  private readonly rateLimiter: AccountRateLimiter;
  private readonly health: HealthMonitor;
  private readonly warmup?: WarmUp;
  private readonly hardPauseEnabled: boolean;
  private readonly logger: Logger;
  private readonly sleepFn: (ms: number) => Promise<void>;

  constructor(deps: SendGateDeps) {
    this.rateLimiter = deps.rateLimiter;
    this.health = deps.health;
    this.warmup = deps.warmup;
    this.hardPauseEnabled = deps.hardPauseEnabled;
    this.logger = deps.logger;
    this.sleepFn = deps.sleepFn ?? realSleep;
  }

  /**
   * Send `content` to `jid` on the current socket `sock`, gated by
   * WarmUp → Health-pause → account RateLimiter (in that order).
   *
   * Returns the Baileys send result (so `opts.track` callers can read
   * `key.id` off it for feedback correlation), or `undefined` when the gate
   * deferred the send — deferring is a silent no-op from the caller's point
   * of view (structured `warn` log, no user text, no raw JID), never a throw.
   * A genuine `sock.sendMessage` failure is recorded on `health` and then
   * rethrown so the caller decides whether to swallow it (as today).
   */
  async send(
    sock: WASocket,
    jid: string,
    content: string,
    opts?: { track?: boolean },
  ): Promise<SendGateResult | undefined> {
    if (this.warmup && !this.warmup.canSend()) {
      this.logger.warn(
        { gate: "warmup", track: Boolean(opts?.track) },
        "send deferred — warm-up cap reached",
      );
      return undefined;
    }

    if (this.hardPauseEnabled && this.health.isPaused()) {
      this.logger.warn(
        { gate: "health", track: Boolean(opts?.track) },
        "send deferred — health hard-pause active",
      );
      return undefined;
    }

    const delay = await this.rateLimiter.getDelay(jid, content);
    if (delay === -1) {
      this.logger.warn(
        { gate: "rateLimiter", track: Boolean(opts?.track) },
        "send deferred — account rate limit exceeded",
      );
      return undefined;
    }
    if (delay > 0) {
      await this.sleepFn(delay);
    }

    try {
      const result = (await sock.sendMessage(jid, { text: content })) as
        | SendGateResult
        | undefined;
      this.rateLimiter.record(jid, content);
      this.warmup?.record();
      return result;
    } catch (err) {
      this.health.recordMessageFailed((err as Error)?.message);
      throw err;
    }
  }
}
