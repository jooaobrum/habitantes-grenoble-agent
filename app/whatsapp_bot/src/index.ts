/**
 * Entrypoint for the WhatsApp (Baileys) channel.
 *
 * Wires the pieces together and owns the long-lived state:
 *   config → logger → API client + guards + feedback maps → connection → handlers
 *   + a heartbeat loop and a periodic cleanup timer + graceful shutdown.
 *
 * The adapter is a thin channel: no agent logic lives here (it is all behind the
 * FastAPI `/chat` endpoint). This file only keeps the socket alive and relays.
 */
import pino from "pino";

import { shouldAlert } from "./alertGate.js";
import { ApiClient } from "./api.js";
import {
  HealthMonitor,
  type BanRiskLevel,
  type HealthStatus,
} from "./antiban/health.js";
import { RateLimiter as AccountRateLimiter } from "./antiban/rateLimiter.js";
import { WarmUp } from "./antiban/warmup.js";
import { WebhookAlerts, type WebhookConfig } from "./antiban/webhooks.js";
import { loadSettings } from "./config.js";
import { startConnection } from "./connection.js";
import { DedupSet, KeyedLock, RateLimiter } from "./guards.js";
import { bindHandlers, type HandlerDeps } from "./handlers.js";
import { SendGate } from "./sendGate.js";

/**
 * Maps a `HealthMonitor` ban-risk level to an account `RateLimiter` pacing
 * factor (`adaptLimits`). Kept as a small pure function so the mapping is
 * easy to read/verify in isolation — per design.md's "Health monitor wiring".
 */
function riskToPacingFactor(risk: BanRiskLevel): number {
  switch (risk) {
    case "critical":
      return 0.1;
    case "high":
      return 0.25;
    case "medium":
      return 0.5;
    case "low":
    default:
      return 1.0;
  }
}

async function main(): Promise<void> {
  const settings = loadSettings();

  const logger = pino({
    level: process.env.LOG_LEVEL ?? "info",
    // Structured JSON logs; no user text or raw JIDs are ever logged.
    base: { service: "whatsapp_bot" },
  });

  if (!settings.adminToken) {
    logger.warn(
      "ADMIN_TOKEN is not set — heartbeats will be rejected by the API",
    );
  }

  const api = new ApiClient(settings, logger);

  // ── Anti-ban state (Phase 2): process-lived, like rateLimiter/dedup/locks ──
  const { antiban } = settings.whatsapp;
  const accountRateLimiter = new AccountRateLimiter({
    maxPerMinute: antiban.account.max_per_minute,
    maxPerHour: antiban.account.max_per_hour,
    maxPerDay: antiban.account.max_per_day,
    minDelayMs: antiban.account.min_delay_ms,
    maxDelayMs: antiban.account.max_delay_ms,
  });

  // Alert transport (A3.3): built from the resolved `alertTransport` (yaml
  // policy + env secrets, pre-merged by config.ts). When disabled (secrets
  // absent) `alerts.alert()` naturally no-ops — no `telegram`/`discord`/`urls`
  // configured — so the object is still constructed, just inert.
  const { alertTransport } = settings.whatsapp;
  const alerts = new WebhookAlerts({
    minRiskLevel: alertTransport.minRiskLevel as WebhookConfig["minRiskLevel"],
    cooldownMs: alertTransport.cooldownMs,
    ...(alertTransport.enabled
      ? {
          telegram: {
            botToken: alertTransport.telegramBotToken!,
            chatId: alertTransport.telegramChatId!,
          },
        }
      : {}),
  });
  if (!alertTransport.enabled) {
    logger.warn(
      "WhatsApp anti-ban alert transport is disabled (WHATSAPP_ALERT_TG_BOT_TOKEN / " +
        "WHATSAPP_ALERT_TG_CHAT_ID not set) — risk alerts will not be delivered; the bot runs normally",
    );
  }
  // Local shadow of `WebhookAlerts`'s private `lastAlertTime`, for the
  // `shouldAlert` logging mirror only (see `handleAntibanRiskChange` below) —
  // the real `alerts` instance tracks its own, authoritative last-alert time.
  let lastLoggedAlertTime = 0;

  /**
   * Reacts to a `HealthMonitor` risk-level transition: fires an alert (subject
   * to the transport's own cooldown/minRiskLevel gating) and adapts the
   * account rate limiter's pacing so the number slows down on its own and
   * speeds back up once risk decays back to `low`. Declared as a closure
   * inside `main()` (rather than top-level) because it needs `accountRateLimiter`
   * and `alerts`, both constructed here — `HealthMonitor` has no setter for
   * `onRiskChange`, only a constructor option, so this must exist before
   * `health` is constructed below.
   */
  function handleAntibanRiskChange(status: HealthStatus): void {
    const factor = riskToPacingFactor(status.risk);
    accountRateLimiter.adaptLimits(factor);
    logger.info(
      { risk: status.risk, score: status.score, factor },
      "antiban risk level changed — adapting account send pacing",
    );

    // `WebhookAlerts.alert()` (vendored, not modifiable) silently no-ops when
    // below `minRiskLevel` or inside `cooldownMs`, with no way to observe
    // which happened from outside. `shouldAlert` is a duplicate, approximate
    // mirror of that same gate — for logging only — so this line is always
    // still followed by the real `alerts.alert(status)` call below,
    // regardless of what it decides.
    const alertDecision = shouldAlert(
      status.risk,
      alertTransport.minRiskLevel,
      Date.now() - lastLoggedAlertTime,
      alertTransport.cooldownMs,
    );
    if (alertDecision === "sent") lastLoggedAlertTime = Date.now();
    logger.info(
      { risk: status.risk, score: status.score, alert: alertDecision },
      "antiban alert gate evaluated",
    );

    void alerts.alert(status).catch((err) => {
      logger.warn(
        { err: (err as Error)?.message },
        "failed to send antiban risk alert",
      );
    });
  }

  const health = new HealthMonitor({
    disconnectWarningThreshold: antiban.health.disconnect_warning_threshold,
    disconnectCriticalThreshold: antiban.health.disconnect_critical_threshold,
    failedMessageThreshold: antiban.health.failed_message_threshold,
    autoPauseAt: antiban.health.auto_pause_at as BanRiskLevel,
    onRiskChange: handleAntibanRiskChange,
  });
  const warmup = antiban.warmup.enabled
    ? new WarmUp({
        day1Limit: antiban.warmup.day1_limit,
        warmUpDays: antiban.warmup.warmup_days,
        inactivityThresholdHours: antiban.warmup.inactivity_threshold_hours,
      })
    : undefined;
  const sendGate = new SendGate({
    rateLimiter: accountRateLimiter,
    health,
    warmup,
    hardPauseEnabled: antiban.health.hard_pause_enabled,
    logger,
  });

  // Long-lived state, shared across reconnects (owned here, passed into deps).
  const deps: HandlerDeps = {
    settings,
    logger,
    api,
    rateLimiter: new RateLimiter(settings.whatsapp.rate_limit_per_minute),
    dedup: new DedupSet(),
    locks: new KeyedLock(),
    sendGate,
    answerToChat: new Map(),
    lastTurn: new Map(),
  };

  // ── Heartbeat loop (best-effort; a failed post never crashes the bot) ──────
  const heartbeatMs = settings.whatsapp.heartbeat_interval_seconds * 1000;
  void api.postHeartbeat(); // fire one immediately
  let heartbeatTimer: NodeJS.Timeout | undefined = setInterval(() => {
    void api.postHeartbeat();
  }, heartbeatMs);

  // ── Periodic cleanup so dedup/rate-limit state doesn't grow unbounded ──────
  const cleanupTimer = setInterval(
    () => {
      deps.dedup.clear();
      deps.rateLimiter.cleanup();
      // Bound the feedback maps too (correlation only matters short-term).
      if (deps.answerToChat.size > 5000) deps.answerToChat.clear();
      if (deps.lastTurn.size > 5000) deps.lastTurn.clear();
      // The account RateLimiter's `cleanup()` is private and self-invoked on
      // every `getDelay()`/`getStats()` call — already satisfied during
      // normal sending. Calling `getStats()` here just nudges that same
      // internal cleanup during quiet periods with no sends, so message
      // history doesn't linger unbounded on an idle number.
      accountRateLimiter.getStats();
    },
    60 * 60 * 1000, // hourly, matching the Telegram bot
  );

  // ── Connection: (re)bind handlers on every socket (initial + reconnects) ───
  const conn = await startConnection(settings, logger, {
    onSocket: (sock) => bindHandlers(sock, deps),
    onOpen: () => {
      logger.info("channel ready — accepting DMs");
      health.recordReconnect();
    },
    onLoggedOut: () => {
      // Stop heartbeating so the control center flips the channel to `critical`
      // via the staleness window (the number needs a fresh QR to work again).
      if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
        heartbeatTimer = undefined;
      }
      logger.warn(
        "logged out — heartbeat stopped; re-pair required (delete auth dir + restart)",
      );
      health.recordDisconnect("loggedOut");
    },
    onDisconnect: (statusCode) => {
      health.recordDisconnect(statusCode ?? "unknown");
    },
  });

  // ── Graceful shutdown ──────────────────────────────────────────────────────
  let shuttingDown = false;
  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info({ signal }, "shutting down");
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    clearInterval(cleanupTimer);
    try {
      await conn.close();
    } catch (err) {
      logger.warn({ err: (err as Error)?.message }, "error during socket close");
    }
    process.exit(0);
  };

  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((err) => {
  // Startup failed (bad config, missing salt, etc.) — fail loudly.
  console.error("fatal: failed to start whatsapp bot:", err);
  process.exit(1);
});
