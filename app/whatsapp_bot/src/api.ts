/**
 * Thin, typed HTTP client for the FastAPI backend.
 *
 * This is a *channel adapter tool*: it only translates typed inputs into HTTP
 * calls and back into typed results. It holds no orchestration logic and never
 * throws — every method resolves to a structured result the caller can branch on.
 *
 * Mirrors the calls the Telegram bot makes (`app/telegram_bot.py`):
 *   - POST {api_url}/chat/       body {chat_id, message, message_id}  header X-Chat-Id
 *   - POST {api_url}/chat/reset  body {chat_id}                       header X-Chat-Id
 *   - POST {api_url}/feedback/   body {chat_id, message_id, rating}    header X-Chat-Id
 *   - POST {api_url}/admin/heartbeat  body {service}                  header X-Admin-Token
 */

import type { Logger } from "pino";

import type {
  ChatResponse,
  FeedbackRating,
  PostChatResult,
  Settings,
} from "./types.js";

/** Minimal structural logger — accepts a pino Logger or any warn/info shim. */
type MinimalLogger =
  | Logger
  | {
      warn: (...args: unknown[]) => void;
      info?: (...args: unknown[]) => void;
    };

/** Fixed heartbeat timeout, matching the Telegram bot's 10.0s heartbeat client. */
const HEARTBEAT_TIMEOUT_MS = 10_000;

export class ApiClient {
  private readonly baseUrl: string;
  private readonly adminToken: string;
  private readonly requestTimeoutMs: number;
  private readonly logger?: MinimalLogger;

  constructor(settings: Settings, logger?: MinimalLogger) {
    // Strip trailing slashes so we can join paths without doubling them.
    this.baseUrl = settings.whatsapp.api_url.replace(/\/+$/, "");
    this.adminToken = settings.adminToken;
    // chat/feedback get the API timeout + 5s of headroom, like the Telegram bot.
    this.requestTimeoutMs = (settings.request_timeout_seconds + 5) * 1000;
    this.logger = logger;
  }

  /** Join the base URL with a path, avoiding double slashes. */
  private url(path: string): string {
    return `${this.baseUrl}/${path.replace(/^\/+/, "")}`;
  }

  private warn(msg: string, fields?: Record<string, unknown>): void {
    if (this.logger) {
      this.logger.warn(fields ?? {}, msg);
    } else {
      console.warn(msg, fields ?? "");
    }
  }

  /**
   * POST /chat/ — send a user message and get the agent's answer.
   *
   * Never throws. On success returns `{ ok: true, data }`; on any HTTP error,
   * network failure, or timeout returns a structured `{ ok: false, ... }`.
   * The bot kill switch surfaces as `error_code: "BOT_DISABLED"`.
   */
  async postChat(input: {
    chatId: string;
    message: string;
    messageId: string;
  }): Promise<PostChatResult> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.requestTimeoutMs);

    try {
      const response = await fetch(this.url("/chat/"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Chat-Id": input.chatId,
        },
        body: JSON.stringify({
          chat_id: input.chatId,
          message: input.message,
          message_id: input.messageId,
        }),
        signal: controller.signal,
      });

      if (response.status === 200) {
        const data = (await response.json()) as ChatResponse;
        this.logger?.info?.(
          { status: 200, trace_id: data.trace_id, cached: data.cached },
          "chat ok",
        );
        return { ok: true, data };
      }

      // Non-200: try to extract a structured error from the body.
      const body = await this.safeJson(response);
      const parsed = this.parseError(response.status, body);
      this.warn("chat request failed", {
        status: response.status,
        error_code: parsed.error_code,
        retryable: parsed.retryable,
      });
      return { ok: false, ...parsed };
    } catch (err) {
      const parsed = this.parseNetworkError(err);
      this.warn("chat request errored", { error_code: parsed.error_code });
      return { ok: false, ...parsed };
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * POST /feedback/ — record a 👍/👎 rating. Best-effort.
   * Returns true on HTTP 200, false otherwise. Never throws.
   */
  async postFeedback(input: {
    chatId: string;
    messageId: string;
    rating: FeedbackRating;
  }): Promise<boolean> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.requestTimeoutMs);

    try {
      const response = await fetch(this.url("/feedback/"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Chat-Id": input.chatId,
        },
        body: JSON.stringify({
          chat_id: input.chatId,
          message_id: input.messageId,
          rating: input.rating,
        }),
        signal: controller.signal,
      });

      if (response.status !== 200) {
        this.warn("feedback request rejected", { status: response.status });
        return false;
      }
      return true;
    } catch (err) {
      this.warn("feedback request errored", {
        error_code: this.parseNetworkError(err).error_code,
      });
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * POST /chat/reset — clear a chat's agent-side memory. Best-effort.
   * Returns true on HTTP 200, false otherwise. Never throws.
   */
  async postReset(input: { chatId: string }): Promise<boolean> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.requestTimeoutMs);

    try {
      const response = await fetch(this.url("/chat/reset"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Chat-Id": input.chatId,
        },
        body: JSON.stringify({ chat_id: input.chatId }),
        signal: controller.signal,
      });

      if (response.status !== 200) {
        this.warn("reset request rejected", { status: response.status });
        return false;
      }
      return true;
    } catch (err) {
      this.warn("reset request errored", {
        error_code: this.parseNetworkError(err).error_code,
      });
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * POST /admin/heartbeat — signal liveness to the API. Best-effort.
   * Returns true on HTTP 200, false otherwise. Never throws.
   */
  async postHeartbeat(): Promise<boolean> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), HEARTBEAT_TIMEOUT_MS);

    try {
      const response = await fetch(this.url("/admin/heartbeat"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Admin-Token": this.adminToken,
        },
        body: JSON.stringify({ service: "whatsapp_bot" }),
        signal: controller.signal,
      });

      if (response.status !== 200) {
        this.warn("heartbeat rejected", { status: response.status });
        return false;
      }
      return true;
    } catch (err) {
      this.warn("heartbeat errored", {
        error_code: this.parseNetworkError(err).error_code,
      });
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  /** Parse a response body as JSON, returning undefined on any failure. */
  private async safeJson(response: Response): Promise<unknown> {
    try {
      return await response.json();
    } catch {
      return undefined;
    }
  }

  /**
   * Normalize a non-200 API response into a structured error.
   *
   * Handles the API's own shape `{ detail: { error_code, message, retryable } }`,
   * the plain `{ detail: "..." }` shape, FastAPI validation errors, and unknown
   * bodies. Defaults: `error_code = "HTTP_<status>"`, `retryable = true` for 5xx
   * and false for 4xx.
   *
   * Kill-switch detection: any `error_code === "BOT_DISABLED"` found in the body,
   * or a 503 whose message mentions the bot being disabled, maps to
   * `error_code: "BOT_DISABLED"`.
   */
  private parseError(
    status: number,
    body: unknown,
  ): { error_code: string; retryable: boolean; message: string } {
    const defaultRetryable = status >= 500;
    let error_code = `HTTP_${status}`;
    let message = `Request failed with status ${status}`;
    let retryable = defaultRetryable;

    const detail = this.getDetail(body);

    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      // Structured error: { error_code, message, retryable }
      const d = detail as Record<string, unknown>;
      if (typeof d.error_code === "string") {
        error_code = d.error_code;
      }
      if (typeof d.message === "string") {
        message = d.message;
      }
      if (typeof d.retryable === "boolean") {
        retryable = d.retryable;
      }
    } else if (typeof detail === "string") {
      // Plain FastAPI HTTPException detail.
      message = detail;
    } else if (Array.isArray(detail)) {
      // FastAPI request-validation error (422): list of error objects.
      message = "Request validation failed";
    }

    // Kill switch: explicit code anywhere in the body, or 503 + disabled message.
    const disabledMention = /disabled/i.test(message);
    if (this.containsBotDisabled(body) || (status === 503 && disabledMention)) {
      error_code = "BOT_DISABLED";
    }

    return { error_code, retryable, message };
  }

  /** Extract a `detail` field from a parsed body, if present. */
  private getDetail(body: unknown): unknown {
    if (body && typeof body === "object" && "detail" in body) {
      return (body as Record<string, unknown>).detail;
    }
    return undefined;
  }

  /** True if `error_code: "BOT_DISABLED"` appears anywhere in the parsed body. */
  private containsBotDisabled(body: unknown): boolean {
    if (!body || typeof body !== "object") {
      return false;
    }
    const record = body as Record<string, unknown>;
    if (record.error_code === "BOT_DISABLED") {
      return true;
    }
    for (const value of Object.values(record)) {
      if (value && typeof value === "object" && this.containsBotDisabled(value)) {
        return true;
      }
    }
    return false;
  }

  /** Map a thrown fetch/abort error into a structured, retryable error. */
  private parseNetworkError(err: unknown): {
    error_code: "TIMEOUT" | "NETWORK";
    retryable: true;
    message: string;
  } {
    const isAbort =
      err instanceof Error &&
      (err.name === "AbortError" || err.name === "TimeoutError");
    if (isAbort) {
      return {
        error_code: "TIMEOUT",
        retryable: true,
        message: "Request timed out",
      };
    }
    return {
      error_code: "NETWORK",
      retryable: true,
      message: err instanceof Error ? err.message : "Network error",
    };
  }
}
