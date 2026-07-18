/**
 * Pure guard/utility functions for the WhatsApp adapter.
 *
 * Every export here is narrow and side-effect-free (except the small in-memory
 * state helpers) — no network, no Baileys, no I/O. This is where the safety
 * critical logic lives (the DM-only "ban firewall"), so each piece is kept
 * simple enough to unit-test in isolation.
 */

import { createHash } from "node:crypto";

/**
 * JID suffixes that mark a 1:1 direct chat (the only kind we serve).
 * - `@s.whatsapp.net` — classic phone-number addressing.
 * - `@lid` — the multi-device "Local ID" addressing WhatsApp now uses for many
 *   1:1 DMs. It identifies an individual (groups are `@g.us`), so it is a DM.
 */
const DM_SUFFIXES = ["@s.whatsapp.net", "@lid"] as const;

/**
 * The single most safety-critical check: is this a real 1:1 DM we may answer?
 *
 * Returns true ONLY for a non-empty JID ending in an individual DM suffix
 * (`@s.whatsapp.net` or `@lid`) that is not from us. Groups (`@g.us`),
 * `status@broadcast`, `@newsletter`, `@broadcast`, empty/undefined JIDs, and any
 * `fromMe` message are all rejected. Be strict: a false positive here means the
 * bot answering inside a group → ban risk.
 */
export function isDirectMessage(
  jid: string | undefined | null,
  fromMe?: boolean,
): boolean {
  if (fromMe === true) return false;
  if (typeof jid !== "string" || jid.length === 0) return false;
  return DM_SUFFIXES.some((suffix) => jid.endsWith(suffix));
}

/**
 * Extract only the leading numeric user part of a JID.
 *
 * Handles `553199999999@s.whatsapp.net`, `553199999999:12@s.whatsapp.net`, and
 * `553199999999.0:12@s.whatsapp.net` — anything after the first `:`, `.`, or `@`
 * (device/agent suffixes) is dropped. Used so the identity hash is stable per
 * user regardless of the linked device.
 */
export function phoneNumberPart(jid: string): string {
  const separatorIndex = jid.search(/[:.@]/);
  return separatorIndex === -1 ? jid : jid.slice(0, separatorIndex);
}

/**
 * Deterministic one-way hash of a JID → the `chat_id` sent across the API.
 *
 * `sha256(salt + phoneNumberPart(jid))`, hex, truncated to `hashLength`. The raw
 * phone number never crosses the API boundary; the salt (env-only) blocks
 * rainbow-table reversal. Same JID always maps to the same `chat_id`.
 */
export function hashJid(jid: string, salt: string, hashLength: number): string {
  const digest = createHash("sha256")
    .update(salt + phoneNumberPart(jid))
    .digest("hex");
  return digest.slice(0, hashLength);
}

/**
 * Sliding-window per-key rate limiter (mirrors Telegram's per-chat throttle).
 *
 * `allow(key)` prunes timestamps older than the window, then rejects (without
 * recording) if the key is already at `maxPerWindow`; otherwise records "now"
 * and allows. `cleanup()` drops empty/expired keys to bound memory growth.
 */
export class RateLimiter {
  private readonly hits = new Map<string, number[]>();

  constructor(
    private readonly maxPerWindow: number,
    private readonly windowMs: number = 60_000,
  ) {}

  allow(key: string): boolean {
    const now = Date.now();
    const cutoff = now - this.windowMs;
    const recent = (this.hits.get(key) ?? []).filter((ts) => ts > cutoff);

    if (recent.length >= this.maxPerWindow) {
      // Keep the pruned list so repeated rejections stay cheap; do NOT record.
      this.hits.set(key, recent);
      return false;
    }

    recent.push(now);
    this.hits.set(key, recent);
    return true;
  }

  /** Remove keys whose timestamps have all aged out of the window. */
  cleanup(): void {
    const cutoff = Date.now() - this.windowMs;
    for (const [key, timestamps] of this.hits) {
      const recent = timestamps.filter((ts) => ts > cutoff);
      if (recent.length === 0) this.hits.delete(key);
      else this.hits.set(key, recent);
    }
  }
}

/**
 * In-memory dedup set keyed by WhatsApp message id.
 *
 * WhatsApp re-delivers messages; this makes processing idempotent. Kept as a
 * class (not a bare Set) so `index.ts` can `clear()` it on a periodic timer.
 */
export class DedupSet {
  private readonly ids = new Set<string>();

  has(id: string): boolean {
    return this.ids.has(id);
  }

  add(id: string): void {
    this.ids.add(id);
  }

  clear(): void {
    this.ids.clear();
  }

  get size(): number {
    return this.ids.size;
  }
}

/**
 * Per-key serial lock so one JID is processed one message at a time.
 *
 * Chains promises per key: same-key jobs run sequentially, different keys run
 * concurrently. The chain entry is removed once the last queued job for a key
 * settles, so the internal Map does not grow unbounded.
 */
export class KeyedLock {
  private readonly chains = new Map<string, Promise<unknown>>();

  run<T>(key: string, fn: () => Promise<T>): Promise<T> {
    const previous = this.chains.get(key) ?? Promise.resolve();
    // Swallow the previous result/error so our turn always runs after it.
    const result = previous.then(() => fn());

    // Track the tail of the chain so cleanup only fires for the last job.
    const tail = result.catch(() => undefined);
    this.chains.set(key, tail);
    void tail.then(() => {
      if (this.chains.get(key) === tail) this.chains.delete(key);
    });

    return result;
  }
}

/** True when the text is longer than the allowed maximum. */
export function exceedsLength(text: string, maxLength: number): boolean {
  return text.length > maxLength;
}

/**
 * Normalize text for gratitude matching: lowercase, strip accents/diacritics,
 * collapse punctuation to spaces, and trim. Emoji are preserved (we don't strip
 * non-ascii wholesale — 🙏/👍 must survive to match emoji-only keywords).
 */
export function normalizeText(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    // Turn ascii punctuation into spaces so tokens are clean; keep letters,
    // digits, whitespace and everything non-ascii (emoji, etc.) intact.
    .replace(/[!-/:-@[-`{-~]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * True when the message is ESSENTIALLY ONLY gratitude (Phase 6 feedback signal).
 *
 * After normalizing, the message must be short (≤ 4 tokens) AND either the whole
 * normalized string is a keyword, or every token is a keyword, or an emoji token
 * present is a keyword. Multi-word keywords ("muito obrigado", "thank you") match
 * as a whole. A real question ("obrigado, mas e o visto?") returns false because
 * it carries non-gratitude tokens / exceeds the length cap.
 */
export function isGratitudeOnly(text: string, keywords: string[]): boolean {
  const normalized = normalizeText(text);
  if (normalized.length === 0) return false;

  const keywordSet = new Set(
    keywords.map((k) => normalizeText(k)).filter((k) => k.length > 0),
  );
  if (keywordSet.size === 0) return false;

  // Whole-message match handles multi-word keywords ("thank you", "muito obrigado").
  if (keywordSet.has(normalized)) return true;

  const tokens = normalized.split(" ");
  if (tokens.length > 4) return false;

  // Every significant token must itself be a gratitude keyword.
  return tokens.every((token) => keywordSet.has(token));
}

/**
 * True when the message is (only) the reset command — `/reset` or bare `reset`,
 * case/accent-insensitive. `normalizeText` already strips the leading `/` (ascii
 * punctuation), so both forms collapse to the same check. Deliberately strict
 * (whole-message match only, no keyword list) — this is a fixed command, not a
 * fuzzy natural-language signal like gratitude.
 */
export function isResetCommand(text: string): boolean {
  return normalizeText(text) === "reset";
}
