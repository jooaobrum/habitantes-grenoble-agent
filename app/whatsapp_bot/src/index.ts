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

import { ApiClient } from "./api.js";
import { loadSettings } from "./config.js";
import { startConnection } from "./connection.js";
import { DedupSet, KeyedLock, RateLimiter } from "./guards.js";
import { bindHandlers, type HandlerDeps } from "./handlers.js";

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

  // Long-lived state, shared across reconnects (owned here, passed into deps).
  const deps: HandlerDeps = {
    settings,
    logger,
    api,
    rateLimiter: new RateLimiter(settings.whatsapp.rate_limit_per_minute),
    dedup: new DedupSet(),
    locks: new KeyedLock(),
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
    },
    60 * 60 * 1000, // hourly, matching the Telegram bot
  );

  // ── Connection: (re)bind handlers on every socket (initial + reconnects) ───
  const conn = await startConnection(settings, logger, {
    onSocket: (sock) => bindHandlers(sock, deps),
    onOpen: () => logger.info("channel ready — accepting DMs"),
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
