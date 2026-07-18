/**
 * Message + feedback handlers for the WhatsApp adapter.
 *
 * This is the channel's translation layer: WhatsApp events → validation/guards →
 * HTTP call to the existing API → WhatsApp reply. It holds NO agent logic (the
 * agent lives behind `POST /chat/`); it only decides *whether* and *how* to relay.
 *
 * `bindHandlers(sock, deps)` is called for every socket (initial + each
 * reconnect), so all mutable state (rate limiter, dedup, locks, feedback maps)
 * lives in `deps` — owned by `index.ts` — and survives reconnects.
 */
import type { WASocket } from "@whiskeysockets/baileys";
import type { Logger } from "pino";

import type { ApiClient } from "./api.js";
import {
  DedupSet,
  KeyedLock,
  RateLimiter,
  exceedsLength,
  hashJid,
  isDirectMessage,
  isGratitudeOnly,
} from "./guards.js";
import type { ChatSource, Settings } from "./types.js";

/** Portuguese user-facing copy — kept identical to the Telegram channel. */
const COPY = {
  oversize: (max: number) =>
    `⚠️ Sua mensagem é muito longa (máximo ${max} caracteres). ` +
    "Por favor, tente resumir sua pergunta.",
  throttle:
    "⏳ Você enviou muitas mensagens em pouco tempo. " +
    "Por favor, aguarde um minuto antes de perguntar novamente.",
  apiError:
    "Desculpe, tive um problema ao processar sua pergunta. " +
    "Por favor, tente novamente em instantes.",
  techError: "Ocorreu um erro técnico. Estamos trabalhando para resolver!",
  disabledFallback:
    "O assistente está temporariamente indisponível. " +
    "Tente novamente mais tarde.",
  gratitude: "De nada! 😊",
} as const;

/** Emoji reactions that map to a rating on a bot answer. */
const UP_EMOJI = new Set(["👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "❤️", "❤", "🙏", "🥰", "😍"]);
const DOWN_EMOJI = new Set(["👎", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿"]);

/**
 * Shared, connection-independent dependencies. Owned by `index.ts` so state
 * (rate limits, dedup, feedback correlation) persists across reconnects.
 */
export interface HandlerDeps {
  settings: Settings;
  logger: Logger;
  api: ApiClient;
  rateLimiter: RateLimiter;
  dedup: DedupSet;
  locks: KeyedLock;
  /** bot answer message id → chat_id (hash), for reaction feedback. */
  answerToChat: Map<string, string>;
  /** raw JID → last answered turn, for gratitude-word feedback. */
  lastTurn: Map<string, { chatId: string; answerMsgId: string }>;
}

/** Random human-like pacing delay within the configured window. */
function pacingDelay(settings: Settings): number {
  const { reply_min_delay_ms: min, reply_max_delay_ms: max } = settings.whatsapp;
  return min + Math.floor(Math.random() * Math.max(0, max - min));
}

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/** Pull plain text from a message, or undefined for non-text / empty messages. */
function extractText(message: unknown): string | undefined {
  const m = message as
    | { conversation?: string; extendedTextMessage?: { text?: string } }
    | null
    | undefined;
  const raw = m?.conversation ?? m?.extendedTextMessage?.text;
  if (typeof raw !== "string") return undefined;
  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

/** Build the reply text: answer + an optional "Fontes" footer (top 3 sources). */
function formatReply(answer: string, sources: ChatSource[]): string {
  if (!sources || sources.length === 0) return answer;
  const lines = sources.slice(0, 3).map((s) => {
    const desc = `${s.category ?? "Geral"} (${s.date ?? "Recente"})`;
    return `• ${desc}`;
  });
  return `${answer}\n\n📚 *Fontes:*\n${lines.join("\n")}`;
}

/**
 * Bind message + reaction handlers to a socket. Idempotent per socket (each
 * reconnect passes a fresh socket, so no double-binding occurs).
 */
export function bindHandlers(sock: WASocket, deps: HandlerDeps): void {
  const { settings, logger, api, rateLimiter, dedup, locks } = deps;
  const { whatsapp } = settings;

  sock.ev.on("messages.upsert", (upsert) => {
    if (upsert.type !== "notify") return;
    for (const msg of upsert.messages) {
      // Never let one message's failure break the loop or crash the process.
      void handleMessage(sock, deps, msg).catch((err) => {
        logger.error(
          { err: (err as Error)?.message },
          "unhandled error while processing a message",
        );
      });
    }
  });

  // Phase 6: reaction feedback (👍/❤️/🙏 → up, 👎 → down) on our own answers.
  sock.ev.on("messages.reaction", (reactions) => {
    for (const r of reactions) {
      void handleReaction(deps, r).catch((err) => {
        logger.warn(
          { err: (err as Error)?.message },
          "unhandled error while processing a reaction",
        );
      });
    }
  });

  logger.info("message + reaction handlers bound to socket");

  // Silence unused-var lint for destructured-but-used-via-deps members.
  void rateLimiter;
  void dedup;
  void locks;
  void whatsapp;
}

/** Core inbound-DM pipeline (see design.md "Message handling"). */
async function handleMessage(
  sock: WASocket,
  deps: HandlerDeps,
  msg: unknown,
): Promise<void> {
  const { settings, logger, api, rateLimiter, dedup, locks, lastTurn, answerToChat } =
    deps;
  const { whatsapp } = settings;

  const m = msg as {
    key?: { remoteJid?: string; fromMe?: boolean; id?: string };
    message?: unknown;
  };
  const jid = m.key?.remoteJid ?? undefined;
  const fromMe = m.key?.fromMe === true;
  const messageId = m.key?.id ?? undefined;

  // 1. DM-only firewall — the single most important guard (spec criterion #2).
  if (!isDirectMessage(jid, fromMe)) return;
  if (!jid || !messageId) return;

  // 2. Extract text; ignore non-text / empty.
  const text = extractText(m.message);
  if (!text) return;

  // 3. Dedup on WhatsApp message id (re-delivery is common).
  if (dedup.has(messageId)) return;
  dedup.add(messageId);

  const chatId = hashJid(jid, settings.idSalt, whatsapp.id_hash_length);

  // 4. Gratitude short-circuit (Phase 6): a "thanks" on the last answered turn
  //    counts as a 👍 and is NOT re-run through the agent.
  if (isGratitudeOnly(text, whatsapp.feedback_positive_keywords)) {
    const turn = lastTurn.get(jid);
    if (turn) {
      const ok = await api.postFeedback({
        chatId: turn.chatId,
        messageId: turn.answerMsgId,
        rating: "up",
      });
      logger.info({ chatId, recorded: ok }, "gratitude feedback recorded");
      await safeSend(sock, jid, COPY.gratitude, logger);
      return;
    }
    // No prior turn to attribute it to → fall through and treat as a question.
  }

  // 5. Length cap → ask to shorten; no API call.
  if (exceedsLength(text, whatsapp.max_message_length)) {
    await safeSend(sock, jid, COPY.oversize(whatsapp.max_message_length), logger);
    return;
  }

  // 6. Per-user rate limit → polite throttle; no API call.
  if (!rateLimiter.allow(jid)) {
    await safeSend(sock, jid, COPY.throttle, logger);
    return;
  }

  // 7. Serialize per JID so one user is processed one message at a time.
  await locks.run(jid, async () => {
    try {
      await sock.sendPresenceUpdate("composing", jid);
      await sleep(pacingDelay(settings)); // human-like pacing

      const result = await api.postChat({ chatId, message: text, messageId });

      if (!result.ok) {
        const reply =
          result.error_code === "BOT_DISABLED"
            ? result.message || COPY.disabledFallback
            : COPY.apiError;
        logger.info(
          { chatId, error_code: result.error_code },
          "relaying API error to user",
        );
        await safeSend(sock, jid, reply, logger);
        return;
      }

      const replyText = formatReply(result.data.answer, result.data.sources);
      const sent = await sock.sendMessage(jid, { text: replyText });

      // Track the answer for feedback correlation (reactions + gratitude).
      const answerMsgId = sent?.key?.id ?? undefined;
      if (answerMsgId) {
        answerToChat.set(answerMsgId, chatId);
        lastTurn.set(jid, { chatId, answerMsgId });
      }
      logger.info(
        { chatId, trace_id: result.data.trace_id, cached: result.data.cached },
        "answer delivered",
      );
    } catch (err) {
      logger.error(
        { chatId, err: (err as Error)?.message },
        "unexpected error handling message",
      );
      await safeSend(sock, jid, COPY.techError, logger);
    } finally {
      // Best-effort: clear typing presence.
      try {
        await sock.sendPresenceUpdate("paused", jid);
      } catch {
        /* ignore */
      }
    }
  });
}

/** Map a reaction on one of our answers to a feedback rating. */
async function handleReaction(
  deps: HandlerDeps,
  reaction: unknown,
): Promise<void> {
  const { api, answerToChat, logger } = deps;
  const r = reaction as {
    key?: { id?: string };
    reaction?: { text?: string };
  };
  const reactedId = r.key?.id;
  const emoji = r.reaction?.text ?? "";
  if (!reactedId) return;

  const chatId = answerToChat.get(reactedId);
  if (!chatId) return; // not one of our answers

  let rating: "up" | "down" | undefined;
  if (UP_EMOJI.has(emoji)) rating = "up";
  else if (DOWN_EMOJI.has(emoji)) rating = "down";
  if (!rating) return; // reaction removed or an emoji we don't map

  const ok = await api.postFeedback({ chatId, messageId: reactedId, rating });
  logger.info({ chatId, rating, recorded: ok }, "reaction feedback recorded");
}

/** Send a text reply, swallowing (but logging) any send failure. Never throws. */
async function safeSend(
  sock: WASocket,
  jid: string,
  text: string,
  logger: Logger,
): Promise<void> {
  try {
    await sock.sendMessage(jid, { text });
  } catch (err) {
    logger.warn({ err: (err as Error)?.message }, "failed to send reply");
  }
}
