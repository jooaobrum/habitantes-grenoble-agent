/**
 * Socket lifecycle owner for the WhatsApp adapter.
 *
 * This module owns everything about *staying connected*: multi-file auth state,
 * credential persistence, QR rendering on first pairing, and the reconnect /
 * loggedOut policy. It contains NO agent logic and makes NO HTTP calls — it just
 * hands the caller a live `WASocket` (via `onSocket`) each time one is created,
 * so `handlers.ts` can (re)bind `messages.upsert` and friends.
 *
 * All tunables come from `settings` (no hardcoded delays). Logging is structured
 * and PII-free: connection-state changes, QR shown, reconnect attempts and
 * loggedOut — never user text, raw JIDs, or phone numbers.
 */
import { mkdirSync } from "node:fs";

import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from "@whiskeysockets/baileys";
import type { WASocket } from "@whiskeysockets/baileys";
import type { Logger } from "pino";
import qrcode from "qrcode-terminal";

import type { Settings } from "./types.js";

/**
 * Callbacks the caller registers so it can react to socket lifecycle events
 * without owning the connection logic itself.
 */
export interface ConnectionCallbacks {
  /** Called with every newly created socket so handlers can (re)bind events. */
  onSocket: (sock: WASocket) => void;
  /** Called when the connection reaches the "open" state. */
  onOpen?: () => void;
  /** Called once when WhatsApp reports a permanent logout (re-pair required). */
  onLoggedOut?: () => void;
  /**
   * Called for every non-intentional close (loggedOut and transient alike)
   * with the Boom `statusCode` (may be `undefined`) so the caller can feed a
   * health/ban-risk monitor. Not called when `close()` was invoked deliberately.
   */
  onDisconnect?: (statusCode: number | undefined) => void;
}

/** Handle returned to the caller for graceful shutdown. */
export interface Connection {
  /** Flush creds (best-effort) and end the socket WITHOUT logging out. */
  close: () => Promise<void>;
}

/** Small non-blocking sleep helper used for reconnect backoff. */
function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

/**
 * Start (and keep alive) the WhatsApp connection.
 *
 * Creates a socket, persists credentials on `creds.update`, renders the pairing
 * QR to logs on first run, and — on disconnect — either stops (loggedOut) or
 * reconnects with capped, jittered exponential backoff. Returns a `close()` that
 * ends the socket cleanly while preserving the session for the next start.
 *
 * @param settings  Resolved adapter settings (auth dir + reconnect delays).
 * @param logger    Pino logger; a silenced child is handed to Baileys.
 * @param callbacks Lifecycle hooks (`onSocket` is required so handlers rebind).
 */
export async function startConnection(
  settings: Settings,
  logger: Logger,
  callbacks: ConnectionCallbacks,
): Promise<Connection> {
  // Auth dir must exist before Baileys tries to read/write it.
  mkdirSync(settings.authDir, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(settings.authDir);

  // Best-effort: pin to the latest known WA web version. Never crash on this.
  let version: [number, number, number] | undefined;
  try {
    ({ version } = await fetchLatestBaileysVersion());
  } catch (err) {
    logger.warn(
      { err: (err as Error)?.message },
      "could not fetch latest Baileys version; using library default",
    );
  }

  // Baileys logs are noisy and can leak protocol detail — silence them; we do
  // our own structured, PII-free logging.
  const baileysLogger = logger.child({ module: "baileys" });
  baileysLogger.level = "silent";

  const { reconnect_base_delay_ms: baseDelay, reconnect_max_delay_ms: maxDelay } =
    settings.whatsapp;

  // Guards against reconnect loops firing after an intentional close().
  let stopped = false;
  // Reference to the current socket so close() can end it.
  let current: WASocket | undefined;
  // Current backoff delay; reset to base on every successful "open".
  let backoff = baseDelay;

  /** Build a fresh socket and wire its lifecycle events. */
  function createSocket(): void {
    const sock = makeWASocket({
      auth: state,
      printQRInTerminal: false, // we render the QR ourselves
      logger: baileysLogger,
      ...(version ? { version } : {}),
    });
    current = sock;

    // Persist credentials — this is what makes the session survive restarts.
    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // First pairing only: render the QR to logs so it is scannable from
        // `docker compose logs`. No user data is involved.
        qrcode.generate(qr, { small: true });
        logger.info(
          "Scan the QR code above with WhatsApp > Linked Devices (first pairing only)",
        );
      }

      if (connection === "open") {
        backoff = baseDelay; // reset the reconnect backoff
        logger.info("whatsapp connection open");
        callbacks.onOpen?.();
        return;
      }

      if (connection === "close") {
        if (stopped) return; // intentional shutdown — do not reconnect

        // Boom error carries the disconnect reason as an HTTP-like statusCode.
        const statusCode = (lastDisconnect?.error as any)?.output?.statusCode;

        // Notify for every non-intentional close (loggedOut and transient
        // alike) so a health/ban-risk monitor sees every disconnect.
        callbacks.onDisconnect?.(statusCode);

        if (statusCode === DisconnectReason.loggedOut) {
          logger.warn(
            "Session logged out — re-pair required (delete the auth dir and restart to scan a fresh QR)",
          );
          callbacks.onLoggedOut?.();
          return; // do NOT reconnect
        }

        // Transient disconnect → reconnect with capped, jittered backoff.
        const jitter = Math.floor(Math.random() * baseDelay);
        const delay = Math.min(backoff, maxDelay) + jitter;
        logger.info(
          { statusCode, delayMs: delay },
          "whatsapp connection closed; scheduling reconnect",
        );

        void sleep(delay).then(() => {
          if (stopped) return;
          // Double for next attempt, capped at max, then rebuild the socket.
          backoff = Math.min(backoff * 2, maxDelay);
          createSocket();
        });
      }
    });

    // Let the caller (re)bind message handlers to the new socket.
    callbacks.onSocket(sock);
  }

  createSocket();

  return {
    async close(): Promise<void> {
      stopped = true; // block any pending reconnect from firing
      try {
        await saveCreds(); // best-effort flush so the session persists
      } catch (err) {
        logger.warn(
          { err: (err as Error)?.message },
          "failed to flush creds on shutdown",
        );
      }
      // End the socket WITHOUT logging out — the session must survive restarts.
      current?.end(undefined);
      logger.info("whatsapp connection closed (session preserved)");
    },
  };
}
