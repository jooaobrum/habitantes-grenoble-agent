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

import type { Settings, WhatsAppSettings } from "./types.js";

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
