/**
 * Shared type contracts for the WhatsApp adapter.
 *
 * These are the *boundaries* between modules (config, guards, api, connection,
 * handlers). Every module depends on these interfaces, never on another
 * module's concrete implementation — mirrors the repo's dependency-inversion rule.
 */

/** `whatsapp.antiban.account` — account-wide RateLimiter budget/pacing. */
export interface WhatsAppAntibanAccountSettings {
  max_per_minute: number;
  max_per_hour: number;
  max_per_day: number;
  min_delay_ms: number;
  max_delay_ms: number;
}

/** `whatsapp.antiban.health` — connection-health ban-risk thresholds. */
export interface WhatsAppAntibanHealthSettings {
  disconnect_warning_threshold: number;
  disconnect_critical_threshold: number;
  failed_message_threshold: number;
  auto_pause_at: string;
  hard_pause_enabled: boolean;
}

/** `whatsapp.antiban.warmup` — post-repair burst safety valve. */
export interface WhatsAppAntibanWarmupSettings {
  enabled: boolean;
  day1_limit: number;
  warmup_days: number;
  inactivity_threshold_hours: number;
}

/** `whatsapp.antiban.alerts` — yaml-mirrored alert policy (no secrets here). */
export interface WhatsAppAntibanAlertsSettings {
  min_risk_level: string;
  cooldown_ms: number;
  transport: string;
}

/** Resolved `whatsapp.antiban` block from config/base.yaml. */
export interface WhatsAppAntibanSettings {
  account: WhatsAppAntibanAccountSettings;
  health: WhatsAppAntibanHealthSettings;
  warmup: WhatsAppAntibanWarmupSettings;
  alerts: WhatsAppAntibanAlertsSettings;
}

/**
 * Resolved alert transport: yaml policy (`min_risk_level`/`cooldown_ms`) merged
 * with the env-only Telegram secrets. `enabled` is false whenever either secret
 * is absent — alerting is optional, so a missing secret never throws (unlike
 * `WHATSAPP_ID_SALT`). Shaped so a later phase can build `WebhookAlerts` from it
 * directly.
 */
export interface WhatsAppAlertTransportSettings {
  enabled: boolean;
  telegramBotToken?: string;
  telegramChatId?: string;
  minRiskLevel: string;
  cooldownMs: number;
}

/** Resolved `whatsapp:` block from config/base.yaml + env overrides. */
export interface WhatsAppSettings {
  api_url: string;
  rate_limit_per_minute: number;
  max_message_length: number;
  reconnect_base_delay_ms: number;
  reconnect_max_delay_ms: number;
  reply_min_delay_ms: number;
  reply_max_delay_ms: number;
  auth_dir: string;
  heartbeat_interval_seconds: number;
  id_hash_length: number;
  feedback_positive_keywords: string[];
  /** Anti-ban hardening config (yaml-mirrored; secrets resolved separately). */
  antiban: WhatsAppAntibanSettings;
  /** Resolved alert transport — yaml policy + env secrets, pre-merged. */
  alertTransport: WhatsAppAlertTransportSettings;
}

/** Top-level resolved settings the adapter needs. */
export interface Settings {
  whatsapp: WhatsAppSettings;
  /** From api.request_timeout_seconds in base.yaml (default 30). */
  request_timeout_seconds: number;
  /** Absolute path to the auth dir (auth_dir resolved against repo root). */
  authDir: string;
  /** WHATSAPP_ID_SALT (env only). Empty string means "not set" — fail loudly. */
  idSalt: string;
  /** ADMIN_TOKEN (env only) for the heartbeat call. */
  adminToken: string;
}

/** A source item as returned by POST /chat/. */
export interface ChatSource {
  category?: string | null;
  date?: string | null;
  text_snippet?: string | null;
  [k: string]: unknown;
}

/** Response body of POST /chat/. */
export interface ChatResponse {
  answer: string;
  sources: ChatSource[];
  intent?: string;
  category?: string;
  confidence?: number;
  trace_id?: string;
  cached?: boolean;
}

/** Result of the API client's postChat: either an answer or a structured error. */
export type PostChatResult =
  | { ok: true; data: ChatResponse }
  | { ok: false; error_code: string; retryable: boolean; message: string };

export type FeedbackRating = "up" | "down";
