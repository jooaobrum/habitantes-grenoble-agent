# WhatsApp Bot (Baileys)

A **DM-only WhatsApp channel** for the *Habitantes de Grenoble* agent. It is a
**thin adapter** in the exact same role as `app/telegram_bot.py`: it holds no
agent logic and only translates WhatsApp events into HTTP calls to the existing
FastAPI backend:

- inbound DM  → `POST /chat/`
- reactions / gratitude replies → `POST /feedback/`
- liveness → `POST /admin/heartbeat` every ~30s (so the control center can
  detect a stale/dead channel)

Boundary respected: `UI (this adapter) → API → Orchestrator → Tools`. The raw
WhatsApp JID never crosses the API boundary — only a salted hash does.

## Prerequisites

- **A DEDICATED, THROWAWAY WhatsApp number.** Never use a personal number. This
  runs on the *unofficial* WhatsApp API (Baileys); if WhatsApp flags it, the ban
  is **permanent**. Use a spare SIM / virtual number you can afford to lose.
- **Node 20+** for local development.

## Required environment (`.env` at the repo root)

| Var | Purpose |
|---|---|
| `WHATSAPP_ID_SALT` | Long random string. Salts the SHA-256 hash of each JID so `chat_id`s are not reversible via a rainbow table of phone numbers. **Required** — the bot fails loudly on startup if unset. |
| `ADMIN_TOKEN` | Auth for `POST /admin/heartbeat`. |
| `API_URL` | Backend base URL. **Forced to `http://api:8000` by docker-compose** (in-network host), so any `.env` value is only used for running outside Docker. |

## Local development

```bash
cd app/whatsapp_bot
npm install
npm run build        # tsc -> dist/
node dist/index.js
# or, without a build step:
npm run dev          # tsx src/index.ts
```

Run from the repo root context so the config loader finds `config/base.yaml`
(it resolves the repo root as three levels up from the source/`dist` file, and
also honors `CONFIG_DIR`).

### Pairing (first run)

On the **first** start there is no saved session, so a **QR code prints in the
logs**. To link the throwaway phone:

1. Open WhatsApp on the throwaway phone.
2. **Settings → Linked Devices → "Link a device".**
3. Scan the QR code shown in the terminal.

After a successful scan, the bot logs `connection: open` and writes the session
to `artifacts/whatsapp/auth/`. **Subsequent restarts reconnect automatically
with no new QR.**

## Docker

```bash
docker compose up whatsapp-bot
# first run — watch for the QR code:
docker compose logs -f whatsapp-bot
```

The compose service builds `app/whatsapp_bot/Dockerfile`, mounts `./config`
(read `base.yaml`) and `./artifacts` (persist the auth session), and forces
`API_URL=http://api:8000`. The container places the code at
`/app/app/whatsapp_bot`, so the config loader resolves the repo root to `/app`
and the auth session lands on the mounted `/app/artifacts` volume.

## Ops notes

- **The auth session is a login secret.** `artifacts/whatsapp/auth/` (e.g.
  `creds.json` + key files) is the equivalent of the linked-device credential.
  It is **git-ignored** (covered by the repo's `artifacts/` rule) — **never
  commit it**. Anyone with these files can impersonate the number.
- **Session persistence.** The session lives on the mounted `./artifacts`
  volume, so rebuilds/restarts do **not** wipe the login (same lesson applied to
  `control.db` via `CONTROL_DB_PATH`).
- **Re-pair required.** If WhatsApp logs the number out, the bot **stops** and
  logs `re-pair required` (it does not loop trying to reconnect). To recover:
  delete the `artifacts/whatsapp/auth/` directory and restart, then scan a fresh
  QR.
- **Heartbeat.** Posts `{ service: "whatsapp_bot" }` every 30s so the control
  center can flag the channel as stale if it goes silent.

## Safety model

- **DM-only** — accepts only `@s.whatsapp.net` chats; never joins, reads, or
  replies in groups (`@g.us`), broadcasts, or newsletters.
- **Reply-only** — never sends unsolicited messages; it only responds to an
  inbound DM.
- **Human-like pacing** — randomized typing/reply delay plus a per-user rate
  limit, to keep volume and cadence modest.
