import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { WebhookAlerts } from "./webhooks.js";

function status(
  risk: string,
  overrides: Partial<{ score: number; recommendation: string; reasons: string[] }> = {},
) {
  return {
    risk,
    score: overrides.score ?? 50,
    recommendation: overrides.recommendation ?? "Reduce messaging rate.",
    reasons: overrides.reasons ?? ["example reason"],
  };
}

describe("WebhookAlerts", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  let originalFetch: typeof fetch;

  beforeEach(() => {
    vi.useFakeTimers();
    originalFetch = global.fetch;
    fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.useRealTimers();
    global.fetch = originalFetch;
  });

  it("does not call fetch when risk is below minRiskLevel", async () => {
    const alerts = new WebhookAlerts({
      minRiskLevel: "high",
      telegram: { botToken: "tok", chatId: "chat" },
    });

    await alerts.alert(status("medium"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("calls fetch and builds a Telegram-shaped payload at/above minRiskLevel", async () => {
    const alerts = new WebhookAlerts({
      minRiskLevel: "high",
      telegram: { botToken: "tok", chatId: "chat-1" },
    });

    await alerts.alert(status("high", { score: 55, reasons: ["3 disconnects in last hour"] }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.telegram.org/bottok/sendMessage");
    const body = JSON.parse(init.body as string);
    expect(body.chat_id).toBe("chat-1");
    expect(body.parse_mode).toBe("Markdown");
    expect(body.text).toContain("HIGH");
    expect(body.text).toContain("55");
    expect(body.text).toContain("3 disconnects in last hour");
  });

  it("suppresses a duplicate alert inside the cooldown window, then allows one after it elapses", async () => {
    const alerts = new WebhookAlerts({
      minRiskLevel: "medium",
      cooldownMs: 60_000,
      telegram: { botToken: "tok", chatId: "chat" },
    });

    await alerts.alert(status("high"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await alerts.alert(status("high")); // still inside cooldown
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 61_000);
    await alerts.alert(status("high")); // cooldown elapsed
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("is a no-op that does not throw when no transport is configured", async () => {
    const alerts = new WebhookAlerts({ minRiskLevel: "low" });

    await expect(alerts.alert(status("critical"))).resolves.toBeUndefined();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
