import { describe, it, expect } from "vitest";
import {
  isDirectMessage,
  phoneNumberPart,
  hashJid,
  RateLimiter,
  DedupSet,
  KeyedLock,
  exceedsLength,
  normalizeText,
  isGratitudeOnly,
} from "./guards.js";

const PHONE = "553199999999";
const DM = `${PHONE}@s.whatsapp.net`;

describe("isDirectMessage", () => {
  it("accepts a real DM JID", () => {
    expect(isDirectMessage(DM)).toBe(true);
    expect(isDirectMessage(`${PHONE}:12@s.whatsapp.net`)).toBe(true);
  });

  it("accepts modern @lid DM addressing", () => {
    // WhatsApp now delivers many 1:1 DMs with a Local-ID (@lid) JID.
    expect(isDirectMessage("123456789012345@lid")).toBe(true);
    expect(isDirectMessage("123456789012345:3@lid")).toBe(true);
  });

  it("rejects groups, status, newsletter, broadcast", () => {
    expect(isDirectMessage("12345@g.us")).toBe(false);
    expect(isDirectMessage("status@broadcast")).toBe(false);
    expect(isDirectMessage("xxx@newsletter")).toBe(false);
    expect(isDirectMessage("xxx@broadcast")).toBe(false);
  });

  it("rejects undefined, null and empty", () => {
    expect(isDirectMessage(undefined)).toBe(false);
    expect(isDirectMessage(null)).toBe(false);
    expect(isDirectMessage("")).toBe(false);
  });

  it("rejects our own messages (fromMe)", () => {
    expect(isDirectMessage(DM, true)).toBe(false);
    expect(isDirectMessage(DM, false)).toBe(true);
  });
});

describe("phoneNumberPart", () => {
  it("strips the suffix and device/agent parts for all JID shapes", () => {
    expect(phoneNumberPart(`${PHONE}@s.whatsapp.net`)).toBe(PHONE);
    expect(phoneNumberPart(`${PHONE}:12@s.whatsapp.net`)).toBe(PHONE);
    expect(phoneNumberPart(`${PHONE}.0:12@s.whatsapp.net`)).toBe(PHONE);
  });
});

describe("hashJid", () => {
  it("is deterministic for the same input", () => {
    expect(hashJid(DM, "salt", 16)).toBe(hashJid(DM, "salt", 16));
  });

  it("changes when the salt changes", () => {
    expect(hashJid(DM, "salt-a", 16)).not.toBe(hashJid(DM, "salt-b", 16));
  });

  it("respects the requested hash length", () => {
    expect(hashJid(DM, "salt", 16)).toHaveLength(16);
    expect(hashJid(DM, "salt", 8)).toHaveLength(8);
  });

  it("never leaks the raw phone number", () => {
    const hash = hashJid(DM, "salt", 16);
    expect(hash).not.toContain(PHONE);
  });

  it("hashes the same user identically regardless of device suffix", () => {
    expect(hashJid(`${PHONE}@s.whatsapp.net`, "salt", 16)).toBe(
      hashJid(`${PHONE}:12@s.whatsapp.net`, "salt", 16),
    );
  });
});

describe("RateLimiter", () => {
  it("allows up to N then blocks N+1 within the window", () => {
    const limiter = new RateLimiter(3, 60_000);
    expect(limiter.allow("k")).toBe(true);
    expect(limiter.allow("k")).toBe(true);
    expect(limiter.allow("k")).toBe(true);
    expect(limiter.allow("k")).toBe(false);
  });

  it("does not consume budget on a rejected call", () => {
    const limiter = new RateLimiter(1, 60_000);
    expect(limiter.allow("k")).toBe(true);
    expect(limiter.allow("k")).toBe(false);
    // still blocked — the rejected call did not add a timestamp
    expect(limiter.allow("k")).toBe(false);
  });

  it("tracks keys independently", () => {
    const limiter = new RateLimiter(1);
    expect(limiter.allow("a")).toBe(true);
    expect(limiter.allow("b")).toBe(true);
    expect(limiter.allow("a")).toBe(false);
  });

  it("cleanup drops keys that have aged out", () => {
    const limiter = new RateLimiter(2, -1); // window in the past → all expired
    limiter.allow("k");
    limiter.cleanup();
    // fresh budget after cleanup
    expect(limiter.allow("k")).toBe(true);
  });
});

describe("DedupSet", () => {
  it("reports has() false before add and true after", () => {
    const dedup = new DedupSet();
    expect(dedup.has("id1")).toBe(false);
    dedup.add("id1");
    expect(dedup.has("id1")).toBe(true);
  });

  it("clear() empties the set", () => {
    const dedup = new DedupSet();
    dedup.add("a");
    dedup.add("b");
    expect(dedup.size).toBe(2);
    dedup.clear();
    expect(dedup.size).toBe(0);
    expect(dedup.has("a")).toBe(false);
  });
});

describe("KeyedLock", () => {
  it("serializes jobs on the same key", async () => {
    const lock = new KeyedLock();
    const order: string[] = [];

    const job = (label: string, delay: number) =>
      lock.run("same", async () => {
        order.push(`${label}:start`);
        await new Promise((r) => setTimeout(r, delay));
        order.push(`${label}:end`);
      });

    // A queued first with a longer delay; B must still wait for A to finish.
    await Promise.all([job("A", 30), job("B", 1)]);

    expect(order).toEqual(["A:start", "A:end", "B:start", "B:end"]);
  });

  it("lets jobs on different keys interleave", async () => {
    const lock = new KeyedLock();
    const order: string[] = [];

    const job = (key: string, label: string, delay: number) =>
      lock.run(key, async () => {
        order.push(`${label}:start`);
        await new Promise((r) => setTimeout(r, delay));
        order.push(`${label}:end`);
      });

    await Promise.all([job("k1", "A", 30), job("k2", "B", 1)]);

    // B (short, other key) should start before A finishes.
    expect(order.indexOf("B:start")).toBeLessThan(order.indexOf("A:end"));
  });

  it("returns the job result", async () => {
    const lock = new KeyedLock();
    await expect(lock.run("k", async () => 42)).resolves.toBe(42);
  });
});

describe("exceedsLength", () => {
  it("is true only when longer than the max", () => {
    expect(exceedsLength("abc", 3)).toBe(false);
    expect(exceedsLength("abcd", 3)).toBe(true);
  });
});

describe("normalizeText", () => {
  it("lowercases, strips accents and collapses punctuation", () => {
    expect(normalizeText("OBRIGADO!!!")).toBe("obrigado");
    expect(normalizeText("ótimo, mesmo?")).toBe("otimo mesmo");
  });

  it("keeps emoji intact", () => {
    expect(normalizeText("🙏")).toBe("🙏");
  });
});

describe("isGratitudeOnly", () => {
  const keywords = [
    "obrigado",
    "muito obrigado",
    "thanks",
    "thank you",
    "merci",
    "gracias",
    "🙏",
    "👍",
  ];

  it("returns true for pure gratitude in several languages", () => {
    for (const msg of [
      "obrigado",
      "muito obrigado",
      "thanks",
      "thank you",
      "merci",
      "gracias",
      "🙏",
      "OBRIGADO!!!",
    ]) {
      expect(isGratitudeOnly(msg, keywords)).toBe(true);
    }
  });

  it("returns false when a real question is attached", () => {
    expect(isGratitudeOnly("obrigado, mas e o visto?", keywords)).toBe(false);
  });

  it("returns false for a normal question", () => {
    expect(isGratitudeOnly("como faço o visto?", keywords)).toBe(false);
  });

  it("returns false for empty or unmatched text", () => {
    expect(isGratitudeOnly("", keywords)).toBe(false);
    expect(isGratitudeOnly("bom dia", keywords)).toBe(false);
  });
});
