/**
 * Config loader for the WhatsApp adapter.
 *
 * Mirrors the Python loader's precedence (habitantes/config.py):
 *   1. read config/base.yaml
 *   2. deep-merge environments[APP_ENV]
 *   3. let specific env vars win (API_URL, ADMIN_TOKEN)
 *
 * Node-only concern — the Python API never reads the `whatsapp:` block, so this
 * is the single place the adapter resolves its settings.
 */
import { readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

import type {
  Settings,
  WhatsAppAlertTransportSettings,
  WhatsAppAntibanSettings,
  WhatsAppSettings,
} from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** Repo root: app/whatsapp_bot/src -> ../../../ ; overridable for Docker via CONFIG_DIR. */
function repoRoot(): string {
  return resolve(__dirname, "..", "..", "..");
}

function deepMerge<T extends Record<string, unknown>>(
  base: T,
  override: Record<string, unknown>,
): T {
  const out: Record<string, unknown> = { ...base };
  for (const [k, v] of Object.entries(override)) {
    const existing = out[k];
    if (
      existing &&
      typeof existing === "object" &&
      !Array.isArray(existing) &&
      v &&
      typeof v === "object" &&
      !Array.isArray(v)
    ) {
      out[k] = deepMerge(
        existing as Record<string, unknown>,
        v as Record<string, unknown>,
      );
    } else {
      out[k] = v;
    }
  }
  return out as T;
}

/** Load and resolve settings. Throws (fails loudly) on missing config or salt. */
export function loadSettings(): Settings {
  const root = repoRoot();
  const configDir = process.env.CONFIG_DIR
    ? process.env.CONFIG_DIR
    : join(root, "config");
  const configPath = join(configDir, "base.yaml");

  const raw = yaml.load(readFileSync(configPath, "utf8")) as Record<
    string,
    unknown
  >;

  const appEnv = process.env.APP_ENV ?? "dev";
  const environments = (raw.environments ?? {}) as Record<
    string,
    Record<string, unknown>
  >;
  const merged = deepMerge(raw, environments[appEnv] ?? {});

  const wa = (merged.whatsapp ?? {}) as Partial<WhatsAppSettings>;
  const apiBlock = (merged.api ?? {}) as { request_timeout_seconds?: number };

  if (!wa || Object.keys(wa).length === 0) {
    throw new Error("config/base.yaml is missing the `whatsapp:` block");
  }

  // API_URL env var wins (docker-compose forces the in-network host).
  const apiUrl = process.env.API_URL ?? wa.api_url ?? "http://api:8000";

  // Anti-ban hardening block. Defaulted here (mirroring base.yaml) so a test
  // fixture missing `antiban:` doesn't crash — base.yaml itself always has it.
  const antibanRaw = (wa.antiban ?? {}) as Partial<WhatsAppAntibanSettings>;
  const accountRaw: Partial<WhatsAppAntibanSettings["account"]> =
    antibanRaw.account ?? {};
  const healthRaw: Partial<WhatsAppAntibanSettings["health"]> =
    antibanRaw.health ?? {};
  const warmupRaw: Partial<WhatsAppAntibanSettings["warmup"]> =
    antibanRaw.warmup ?? {};
  const alertsRaw: Partial<WhatsAppAntibanSettings["alerts"]> =
    antibanRaw.alerts ?? {};

  const antiban: WhatsAppAntibanSettings = {
    account: {
      max_per_minute: accountRaw.max_per_minute ?? 8,
      max_per_hour: accountRaw.max_per_hour ?? 200,
      max_per_day: accountRaw.max_per_day ?? 1500,
      min_delay_ms: accountRaw.min_delay_ms ?? 1500,
      max_delay_ms: accountRaw.max_delay_ms ?? 5000,
    },
    health: {
      disconnect_warning_threshold:
        healthRaw.disconnect_warning_threshold ?? 3,
      disconnect_critical_threshold:
        healthRaw.disconnect_critical_threshold ?? 5,
      failed_message_threshold: healthRaw.failed_message_threshold ?? 5,
      auto_pause_at: healthRaw.auto_pause_at ?? "critical",
      hard_pause_enabled: healthRaw.hard_pause_enabled ?? false,
    },
    warmup: {
      enabled: warmupRaw.enabled ?? true,
      day1_limit: warmupRaw.day1_limit ?? 200,
      warmup_days: warmupRaw.warmup_days ?? 7,
      inactivity_threshold_hours: warmupRaw.inactivity_threshold_hours ?? 72,
    },
    alerts: {
      min_risk_level: alertsRaw.min_risk_level ?? "high",
      cooldown_ms: alertsRaw.cooldown_ms ?? 300000,
      transport: alertsRaw.transport ?? "telegram",
    },
  };

  // Alert secrets: env-only, never yaml (same pattern as WHATSAPP_ID_SALT /
  // ADMIN_TOKEN below). Unlike the salt, a missing secret must NOT throw —
  // alerting is optional, so it simply resolves as disabled.
  const alertTgBotToken = process.env.WHATSAPP_ALERT_TG_BOT_TOKEN ?? "";
  const alertTgChatId = process.env.WHATSAPP_ALERT_TG_CHAT_ID ?? "";
  const alertTransport: WhatsAppAlertTransportSettings = {
    enabled: Boolean(alertTgBotToken && alertTgChatId),
    telegramBotToken: alertTgBotToken || undefined,
    telegramChatId: alertTgChatId || undefined,
    minRiskLevel: antiban.alerts.min_risk_level,
    cooldownMs: antiban.alerts.cooldown_ms,
  };

  const whatsapp: WhatsAppSettings = {
    api_url: apiUrl,
    rate_limit_per_minute: wa.rate_limit_per_minute ?? 5,
    max_message_length: wa.max_message_length ?? 2000,
    reconnect_base_delay_ms: wa.reconnect_base_delay_ms ?? 2000,
    reconnect_max_delay_ms: wa.reconnect_max_delay_ms ?? 60000,
    reply_min_delay_ms: wa.reply_min_delay_ms ?? 600,
    reply_max_delay_ms: wa.reply_max_delay_ms ?? 1800,
    auth_dir: wa.auth_dir ?? "artifacts/whatsapp/auth",
    heartbeat_interval_seconds: wa.heartbeat_interval_seconds ?? 30,
    id_hash_length: wa.id_hash_length ?? 16,
    feedback_positive_keywords: wa.feedback_positive_keywords ?? [],
    antiban,
    alertTransport,
  };

  // Resolve auth_dir against the repo root unless already absolute.
  const authDir = isAbsolute(whatsapp.auth_dir)
    ? whatsapp.auth_dir
    : join(root, whatsapp.auth_dir);

  const idSalt = process.env.WHATSAPP_ID_SALT ?? "";
  if (!idSalt) {
    throw new Error(
      "WHATSAPP_ID_SALT is not set — required to hash JIDs (see .env.example)",
    );
  }

  const adminToken = process.env.ADMIN_TOKEN ?? "";

  return {
    whatsapp,
    request_timeout_seconds: apiBlock.request_timeout_seconds ?? 30,
    authDir,
    idSalt,
    adminToken,
  };
}
