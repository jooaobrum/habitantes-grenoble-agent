# Control Center — Ops Dashboard, Kill Switch & Cost Alerting

**Status:** Draft · **Owner:** 1 engineer (operator) · **Type:** admin/ops surface, served by the existing API, single-operator, no new infra.

## Context — why this exists

The bot is live for a real community with no operational safety net: conversation memory, cache, and rate
limits are in-memory only, there is no cost visibility, `/health` only checks Qdrant, and nothing reacts if
OpenAI spend spikes or a dependency goes down — the operator would find out from a user complaint. This
feature adds a **single control point**: one dashboard to see health + usage + cost, one switch to stop the
bot, and automation that flips that switch and emails the operator the moment a threshold is breached.

A static visual mockup (control bar with the switch, KPI row, service health list, cost trend + budget bar,
top-categories chart, alerts/automation form, alert log) was reviewed and approved on 2026-07-16.

## Decisions

- **One master switch**, not per-service — stops Telegram intake and API chat responses together. Per-service
  switches are out of scope (see below).
- **Persisted in SQLite** (`artifacts/control/control.db`), not Redis/Postgres — no new infra, mirrors the
  precedent set by [kb-management](../kb-management/design.md), and survives an API restart (today's
  `_memory`/cache/rate-limit dicts don't — fixing those is a separate, later effort).
- **Cost is estimated**, not billed — computed from OpenAI token usage attached to each LLM call × a
  configured $/1M price. There is no realtime OpenAI billing API to read from instead.
- **Auto-disable is automatic**, not advisory — the moment a configured threshold trips, the switch flips off
  and the email fires in the same action. Re-enabling is a manual, deliberate click.
- **Dashboard is a static HTML/JS page** (`app/admin/`) calling new token-gated `/admin/*` FastAPI routes —
  not Streamlit. Streamlit is reserved for the offline kb-management console; this surface reads live,
  query-time-adjacent state, so it belongs with the API per the UI→API rule.
- **Single shared `ADMIN_TOKEN`** (env var, header-based) — no user accounts/roles. Matches the existing
  `OPENAI_API_KEY`/`TELEGRAM_BOT_TOKEN` pattern in `config.py`.
- **`/health` is untouched** — it stays the cheap liveness probe Docker's healthcheck already depends on.
  `/admin/status` is the new, richer, token-gated endpoint the dashboard reads.

## What the system does

1. **Kill switch** — `GET/POST /admin/switch` reads/toggles a persisted `enabled` flag. The chat path checks
   it before running the agent; when disabled it returns the structured no-service response without calling
   OpenAI or Qdrant.
2. **Health** — `/admin/status` reports a *measured* status for API (self), Qdrant, OpenAI, and the Telegram
   bot (heartbeat), not an assumed one.
3. **Cost tracking** — every LLM call's token usage is captured into `AgentState` and the interaction log;
   `/admin/status` aggregates today's and this month's estimated cost.
4. **Usage metrics** — requests/hour, cache hit rate, top categories, latency — aggregated from the existing
   `logs/interactions.jsonl`, no new datastore for this part.
5. **Alerting & automation** — a background loop evaluates thresholds (daily cost limit, N consecutive health
   failures) on an interval. On breach: switch off, email sent, alert-log row appended. Thresholds and the
   recipient address are editable from the dashboard and persisted in the same SQLite store.
6. **Alert log** — append-only history of every auto-action and manual admin action, shown in the UI.

## Data contracts

- **`AgentState`** gains `tokens_in: int`, `tokens_out: int`, `cost_usd: float` — computed in `agent.py` from
  the LLM response's usage metadata, never user-supplied. Missing usage (e.g. an SDK response without it) →
  logged as `0`, and never blocks the answer — cost tracking is best-effort by design.
- **`logs/interactions.jsonl`** gains `tokens_in`, `tokens_out`, `cost_usd` per line, additive — existing
  lines simply lack the fields; aggregation treats missing as `0`.
- **`GET /admin/status`** → `AdminStatusResponse`:
  `{ switch: {enabled, changed_at}, services: [{name, status, latency_ms, checked_at}], kpis:
  {requests_today, cache_hit_rate, cost_today_usd, cost_month_usd, budget_daily_usd, budget_monthly_usd,
  uptime_24h_pct}, categories: [{name, count}], thresholds: {...}, alerts: [{timestamp, trigger, action,
  status}] }`.
- **`POST /admin/switch`** body `{enabled: bool}` → `{enabled, changed_at}`.
- **`POST /admin/thresholds`** body `{daily_cost_limit_usd, health_grace_checks, email_to,
  auto_disable_enabled}`, Pydantic-validated (positive numbers, valid email) → 422 on invalid input, no
  partial persistence.
- Missing/invalid `ADMIN_TOKEN` on any `/admin/*` route → `401`, no state change, no partial writes.

## Grounding & evidence

- Health values come from real checks: Qdrant via `get_collections()`, OpenAI via a dedicated lightweight
  ping (isolated from user traffic, so one bad user request can't flip a status flag on its own), Telegram
  bot via a heartbeat it posts on its own poll loop.
- Cost/usage numbers come from logged token counts, never an LLM guess.
- Every alert-log row cites the exact trigger (threshold + measured value) and the action taken.

## Safety & compliance

- **Fail-open on control-store failure**: if the SQLite store can't be read, the chat path treats the bot as
  enabled and logs an error — a broken 200KB local file must not be a new way to take the whole community bot
  down. The failure itself surfaces as a `critical` entry in `/admin/status` so the operator notices and
  fixes it.
- Admin routes require `ADMIN_TOKEN`, compared with `hmac.compare_digest` (no timing side-channel), never
  logged.
- SMTP credentials live in `.env`, never committed, never logged.
- No PII in cost/usage aggregates — category, date, and counts only, matching the existing interaction log.

## Quality metrics

- Offline: unaffected — this feature touches no retrieval/generation logic; `tests/eval/run_eval.py` must
  stay green.
- Product: a switch toggle is reflected on the next chat request within 5s; a threshold breach triggers the
  auto-disable + email within one evaluation cycle (default 60s) of the breach.

## Latency/cost budget

- `/admin/status` p95 < 800ms (log aggregation is bounded by the existing 10MB rotation, never a full-history
  scan).
- The kill-switch check adds ≤5ms to the chat request path (in-process short-TTL cache over the SQLite read,
  not a disk hit per request).
- The OpenAI health ping runs once per health-check interval (default 60s) — never once per chat request, so
  it cannot compound token spend.
- The alert-evaluation loop runs once per interval regardless of chat traffic volume.

## Failure modes + safe behavior

- Control store unreachable → chat continues (fail-open, see Safety); health panel shows the store itself as
  `critical`.
- SMTP send fails → the alert-log row is still written with `email_sent: false` and retried next cycle; the
  switch flips off first, the email is best-effort after — a broken mail relay never blocks the safety action.
- OpenAI/Qdrant/Telegram health checks time out → status `unreachable`, caught and structured, never an
  unhandled exception in the dashboard request.
- Threshold save with invalid values → `422` with a field-level message, no partial persistence.

## Observability

- Every admin action (switch toggle, threshold change, test alert) is appended to the alert log as an audit
  row with a timestamp and what changed.
- The alert-evaluation loop logs at `INFO` every cycle, even when it's a no-op, so "is the watchdog alive" is
  answerable from the logs; a breach logs at `ERROR`.

## Out of scope

- Per-service kill switches — one master switch only.
- Multi-user auth/roles; audit trail beyond the alert log.
- Real OpenAI billing API integration — estimate only, from logged tokens.
- Horizontal scaling / Redis / a distributed switch — single VPS, single API worker, matching today's
  `docker-compose.yml`.
- Historical cost export/CSV; SMS/push notifications (email only, per request).
- Fixing the pre-existing in-memory conversation memory / response cache / rate limiter — only the switch
  gets durable storage in this feature; the rest is tracked separately.

## Done when

- [ ] `POST /admin/switch` toggles a persisted flag; a disabled bot returns the structured no-service message
      on `/chat` without calling OpenAI or Qdrant.
- [ ] `GET /admin/status` returns real health for API/Qdrant/OpenAI/Telegram bot, today's + this month's
      estimated cost, requests/cache-hit-rate/top-categories from the interaction log, current thresholds,
      and the alert log.
- [ ] `agent.py` captures `tokens_in`/`tokens_out`/`cost_usd` into `AgentState` and the interaction log;
      `state.py` updated to match; existing tests and the eval gate are unaffected.
- [ ] A background loop evaluates thresholds every `alerts.interval_seconds`; breaching the daily cost limit
      or N consecutive health failures flips the switch off and sends an email; an alert-log row is appended
      on every breach and every resolution.
- [ ] `app/admin/index.html` (the approved mockup, wired to `/admin/*`) requires `ADMIN_TOKEN` and renders
      real data, including a working switch and a working "send test alert" action.
- [ ] `pytest tests/ -v` and `python tests/eval/run_eval.py` both pass.

## Reference

- Approved visual mockup: static HTML demo reviewed 2026-07-16 (control bar + switch, KPI row, service
  health list, cost trend + budget bar, top-categories chart, alerts/automation form, alert log table).
- Design: [design.md](design.md) · Tasks: [tasks.md](tasks.md)
- SQLite-backed store precedent: [.specs/kb-management/design.md](../kb-management/design.md)
  (`tools/review/store.py`)
- Config: [api/src/habitantes/config.py](../../api/src/habitantes/config.py)
- Interaction logging (extend, don't replace): [api/src/habitantes/infrastructure/logging.py](../../api/src/habitantes/infrastructure/logging.py)
- Chat entry point to gate on the switch: [api/src/habitantes/infrastructure/api/routers/chat.py](../../api/src/habitantes/infrastructure/api/routers/chat.py)
