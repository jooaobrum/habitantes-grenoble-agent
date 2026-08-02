# WhatsApp Cloud API — Setup Runbook

Manual steps in Meta's Business/App dashboards to stand up the WhatsApp Cloud API channel
for this bot. The code side (`infrastructure/whatsapp/`, `routers/webhooks.py`,
`WhatsAppCloudConfig` in `config.py`) is covered in [ARCHITECTURE.md](ARCHITECTURE.md) — this
document is the operational counterpart: where to click in Meta's UI, and which env var each
value maps to. The UI moves around — this records where things were as of 2026, and what each
value maps to. If a step doesn't match what you see, the mapping (which value goes to which
env var, and why) is still the reliable part.

The channel is entirely optional: every secret below defaults to `""`/unset, and
`WhatsAppCloudConfig.enabled` only turns on once all of `WHATSAPP_BUSINESS_TOKEN`,
`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, and
`WHATSAPP_ID_SALT` are set — nothing crashes if you skip this entirely and only run Telegram.

## Prerequisites

- A Meta Business account and a Meta App with the WhatsApp product added.
- A phone number registered to that WhatsApp Business Account (WABA) — either a Meta test
  number or your own.
- The API deployed and reachable (`docker compose up`, including the `cloudflared` service —
  see the [Cloudflare Tunnel](#cloudflare-tunnel-public-ingress) section below). Meta needs a
  live public HTTPS endpoint to POST to *before* the webhook verification step will succeed.

## Finding your Phone Number ID

App Dashboard → Casos de uso → Conectar no WhatsApp → Configuração básica → Etapa 2 →
expand "Registre seu número de telefone". Maps to `WHATSAPP_PHONE_NUMBER_ID`.

## Finding your WABA ID

business.facebook.com/settings/whatsapp-business-accounts/ — table with an ID column.
More reliable than WhatsApp Manager's "Visão geral" screen, which doesn't always show it.
Maps to `WHATSAPP_WABA_ID`. Only needed for number/template management calls, not for sending
or receiving messages — `client.py`'s `send_text`/`mark_read_and_typing` only need
`WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_BUSINESS_TOKEN`.

## Generating a permanent access token

Business Settings → System Users → add a system user → Generate token.
Scopes: `whatsapp_business_messaging`, `whatsapp_business_management`, `business_management`.
Expiration: **Never**. This is NOT the same as the 24h token shown on the API Setup panel —
that one expires and must not be used in production. Maps to `WHATSAPP_BUSINESS_TOKEN`.

## Configuring the webhook in Meta's dashboard

App Dashboard → WhatsApp → Configuration → Webhook:

- **Callback URL**: `https://<your-cloudflare-hostname>/webhooks/whatsapp` (the path is fixed —
  see `routers/webhooks.py`, mounted at `/webhooks` with the `whatsapp` sub-route).
- **Verify token**: whatever you set as `WHATSAPP_VERIFY_TOKEN` (see below).
- Subscribe to the `messages` webhook field at minimum (that's what `processor.py` handles;
  `statuses` — delivery/read receipts — is intentionally ignored by the code and doesn't need
  to be subscribed).

Meta will immediately GET the Callback URL with `hub.mode=subscribe`, `hub.verify_token=...`,
and `hub.challenge=...`. `routers/webhooks.py::verify_webhook` only returns the raw challenge
(as plain text, not JSON — required by Meta's contract) when `hub_verify_token` matches
`WHATSAPP_VERIFY_TOKEN` via a constant-time comparison; otherwise it returns 403. If this step
fails, double-check the API is actually reachable at that public URL first (curl it from
outside your network) before suspecting the token.

## ⚠️ The step that silently breaks everything

Configuring the Callback URL in the webhook settings panel does **NOT** subscribe your app
to that WABA's events — these are two separate actions. Without the second step, the webhook
verifies fine (responds 200 to Meta's GET handshake) and simply never receives any inbound
message, with no error anywhere — not in Meta's UI, not in the API logs, nothing. This is the
single most common reason "the webhook is configured but nothing happens."

After setting the Callback URL and Verify Token, you must also call:

```
POST https://graph.facebook.com/v23.0/{WABA_ID}/subscribed_apps
Authorization: Bearer {WHATSAPP_BUSINESS_TOKEN}
```

(`v23.0` matches this repo's default `whatsapp_cloud.graph_api_version` in `config.py` /
`config/base.yaml` — use whatever version you've actually configured if you've changed it.)

Verify the subscription took with:

```
GET https://graph.facebook.com/v23.0/{WABA_ID}/subscribed_apps
Authorization: Bearer {WHATSAPP_BUSINESS_TOKEN}
```

You should see your app's id in the response. If this app was recreated, or the WABA was
re-linked to a different app, redo this step — the subscription does not persist automatically
across either of those changes.

## App Secret and Verify Token

App Settings → Basic → App Secret → maps to `WHATSAPP_APP_SECRET` (used to verify the
`X-Hub-Signature-256` header on every inbound webhook call — see
`routers/webhooks.py::_verify_signature`, which HMACs the *raw* request body and rejects with
403 on any mismatch or missing header, closed by default if the secret itself is unset).

`WHATSAPP_VERIFY_TOKEN` is a value you invent yourself (e.g. `openssl rand -hex 32`) and
paste into the Meta webhook config panel — Meta echoes it back on the GET handshake to prove
it's really Meta configuring the webhook, not an attacker.

## Cloudflare Tunnel (public ingress)

Meta must be able to POST to your webhook, so the homelab needs a public HTTPS endpoint.
Cloudflare Zero Trust dashboard → Networks → Tunnels → create a named tunnel → copy its
token into `CLOUDFLARE_TUNNEL_TOKEN` (`.env`; consumed directly by the `cloudflared` service
in `docker-compose.yml`, not read by the Python app at all). Recommended: scope the Public
Hostname rule to the webhook path only (Path: `webhooks/*`, Service: `http://api:8000`)
rather than the whole API — `/admin/*` is token-guarded either way, but there's no reason to
expose it publicly.

`cloudflared` dials *out* to Cloudflare's edge (no inbound port to open, no firewall change on
the VPS). If the webhook verification GET from Meta times out, check `docker compose logs
cloudflared` first — a crash-looped tunnel container looks identical to a firewall problem
from Meta's side.

## WHATSAPP_ID_SALT — never rotate

Used to hash the sender's phone number into `chat_id`
(`chat_id = sha256(salt + wa_id)[:hash_length]`, see `guards.py::hash_wa_id`; `hash_length` is
`whatsapp_cloud.id_hash_length`, 16 hex chars by default). Every user's conversation memory
(`agent.py`'s `_memory` dict, while the process is up) and feedback history is keyed off this
hash. Rotating the salt changes every returning user's `chat_id`, which is indistinguishable
from deleting their history. Generate it once (`openssl rand -hex 32`) and never touch it
again — including across a channel migration, which is exactly why this salt is shared with
the format used by any prior WhatsApp adapter this bot has had.

## Testing end-to-end

1. Send a message from your own WhatsApp to the configured business number.
2. Watch `docker compose logs -f api` for `whatsapp_cloud: answer delivered chat_id=...` —
   if you see `whatsapp webhook: signature verification failed`, double check
   `WHATSAPP_APP_SECRET`; if nothing logs at all, you likely missed the `subscribed_apps`
   step above.
3. React with 👍/👎 (or a thumbs-up-equivalent emoji, see `UP_EMOJI`/`DOWN_EMOJI` in
   `processor.py`) on a bot answer to confirm reaction-based feedback is recorded.
4. Send `reset` (bare word, case/accent-insensitive) to confirm it clears memory without going
   through the agent.

## Gotcha: Tailscale full-tunnel mode

Testing the webhook or admin dashboard from a phone with Tailscale in full-tunnel mode can
break access to normal (non-Tailscale) sites while it's on — including the Meta panels
themselves. Toggle it off when doing this setup from a phone.

## Related

- [ARCHITECTURE.md](ARCHITECTURE.md) — the code-side flow (`infrastructure/whatsapp/`,
  webhook router, guards) and how this channel fits into the rest of the system.
- [../README.md](../README.md) — environment variable reference and deployment steps.
