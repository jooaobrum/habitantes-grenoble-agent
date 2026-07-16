# Control Center — Design

See [spec.md](spec.md) for intent and decisions.

## Boundary

No new service in `docker-compose.yml`. Everything lives inside the existing `api` container:

- `domain/control.py` — **pure logic only**, no I/O. Given today's cost + per-service failure streaks +
  thresholds, decides whether to disable. Same separation as `agent.py` (orchestration) vs. `domain/tools/`
  (I/O): this module never touches SQLite, SMTP, or an HTTP client, so it's unit-testable with plain dicts.
- `infrastructure/control_store.py`, `infrastructure/health_checks.py`, `infrastructure/alerts/` — all I/O.
  SQLite, live pings to Qdrant/OpenAI, SMTP. Thin wrappers, no decisions — the decisions live in `control.py`.
- `infrastructure/api/routers/admin.py` — wires the two together behind an `ADMIN_TOKEN` dependency.
- `app/admin/index.html` — the approved mockup, static, calls `/admin/*` only. Never imports anything from
  `domain/`.
- `chat.py` gets one new line: check `control_store.is_enabled()` before calling `run_agent`. It does not
  import `control_store` directly for anything else — same "tools are thin, orchestrator stays thin" rule
  the rest of the codebase already follows.

## Components

```
api/src/habitantes/
  domain/
    control.py              evaluate_thresholds(cost, streaks, thresholds) → BreachResult | None   ← pure
    state.py                + tokens_in, tokens_out, cost_usd                                       ← state
    agent.py                captures usage_metadata from the LLM response into those fields          ← orchestration
    schemas.py               + AdminStatusResponse, SwitchRequest, ThresholdsRequest, HeartbeatRequest

  infrastructure/
    control_store.py        SQLite: switch, thresholds, alert_log, health_snapshot, heartbeat         ← state I/O
    health_checks.py        check_qdrant(), check_openai(), check_telegram_heartbeat(store)            ← probes
    logging.py               + aggregate_usage(since) reading logs/interactions.jsonl                  ← reused by watchdog + admin.py
    alerts/
      email.py              send_alert(subject, body) via stdlib smtplib                               ← I/O
      watchdog.py           background loop: probe → snapshot → evaluate → act                         ← I/O + wiring
    api/
      main.py                mounts admin router + /admin/ui static files, starts the watchdog task
      routers/
        admin.py             GET /admin/status · POST /admin/switch · POST /admin/thresholds ·
                              POST /admin/heartbeat · POST /admin/test-alert  (all token-gated)
        chat.py               + one guard: control_store.is_enabled() before run_agent

app/
  admin/index.html            static dashboard (the approved mockup), fetch() → /admin/*
  telegram_bot.py             + periodic POST /admin/heartbeat on its own poll loop

artifacts/control/control.db  gitignored, mounted volume (same pattern as artifacts/review/)
```

Data flow (watchdog cycle, every `alerts.interval_seconds`):

```
health_checks.check_*() → control_store.write_health_snapshot()
control_store.read_snapshot() + logging.aggregate_usage(today) → control.evaluate_thresholds()
  → BreachResult(trigger, measured) → control_store.set_switch(False, changed_by=trigger)
                                     → control_store.append_alert(...)
                                     → alerts.email.send_alert(...)
```

Data flow (chat request):

```
POST /chat → control_store.is_enabled()  (in-process cache, 5s TTL — avoids a disk read per request)
  → False: structured no-service response, no OpenAI/Qdrant call
  → True:  run_agent as today
```

## `control_store.py` — SQLite schema (`artifacts/control/control.db`)

**`switch`** (singleton, `id = 1`)

| column | notes |
|---|---|
| `enabled` INTEGER | 0/1 |
| `changed_at` TEXT | ISO timestamp |
| `changed_by` TEXT | `"admin"` \| `"watchdog:daily_cost_limit"` \| `"watchdog:health:<service>"` |

**`thresholds`** (singleton, `id = 1`) — matches the spec's `POST /admin/thresholds` contract, plus one
display-only field not in that contract:

| column | notes |
|---|---|
| `daily_cost_limit_usd` REAL | default from `config.alerts.daily_cost_limit_usd` |
| `health_grace_checks` INTEGER | consecutive failed checks before disabling, default `3` |
| `email_to` TEXT | alert recipient |
| `auto_disable_enabled` INTEGER | 0/1 — master switch for the watchdog's *action*, not its monitoring |
| `monthly_budget_usd` REAL | **display-only** — feeds the KPI row's budget bar; not itself an alert trigger in v1 (avoids scope creep beyond the spec's "Done when" list) |
| `updated_at` TEXT | ISO timestamp |

**`alert_log`**

| column | notes |
|---|---|
| `id` INTEGER PK AUTOINCREMENT | |
| `timestamp` TEXT | ISO |
| `trigger` TEXT | e.g. `daily_cost_limit_breach`, `health:openai`, `manual:switch_off`, `manual:switch_on`, `thresholds_updated`, `test_alert` |
| `measured` TEXT | human-readable, e.g. `"€5.12 of €5.00"` or `"3/3 failed checks"` |
| `action` TEXT | `switch_disabled` \| `switch_enabled` \| `logged_only` \| `thresholds_updated` \| `test_email_sent` |
| `email_sent` INTEGER | 0/1/NULL |
| `status` TEXT | `active` \| `resolved` |
| `resolved_at` TEXT | NULL until resolved |

**Resolution rule (refines the spec, doesn't contradict it):** an alert row flips to `resolved` when the
switch is turned back **on** — not automatically when the underlying condition clears. Cost resets naturally
at day rollover but that doesn't mean it's safe to resume; health recovering doesn't either. Re-enabling is
a deliberate admin action per the spec's Decisions, so that's the one place resolution happens: `POST
/admin/switch {enabled: true}` marks every currently-`active` row `resolved`. This keeps the watchdog
edge-triggered and free of spam — once disabled, it evaluates and snapshots every cycle but never re-fires
an alert while already off.

**`health_snapshot`** (one row per service, upserted every cycle)

| column | notes |
|---|---|
| `service` TEXT PK | `api` \| `qdrant` \| `openai` \| `telegram_bot` \| `control_store` |
| `status` TEXT | `ok` \| `degraded` \| `critical` \| `unreachable` |
| `latency_ms` REAL | NULL if unreachable |
| `checked_at` TEXT | ISO |
| `detail` TEXT | short error message, NULL on success |
| `consecutive_failures` INTEGER | reset to 0 on success, incremented on failure — this is what `health_grace_checks` compares against |

`control_store` itself can't self-report into this table if it's the thing that's broken — its row is
written by the *caller* catching the read/write exception (fail-open per spec's Safety section), not by the
store itself.

**`heartbeat`** (one row, `service = 'telegram_bot'`) — `last_seen_at` TEXT, updated by `POST
/admin/heartbeat`. `health_checks.check_telegram_heartbeat()` reads it and reports `critical` if stale beyond
`3 × bot poll interval`.

## `domain/control.py` (pure)

```python
def evaluate_thresholds(
    cost_today_usd: float,
    service_streaks: dict[str, int],   # {"qdrant": 0, "openai": 3, ...}
    thresholds: ThresholdsSnapshot,
) -> BreachResult | None:
```

Returns the **first** breach found (cost checked before health, since a cost breach is the more common and
more urgent case for a community bot) or `None`. No I/O, no `settings`, no SQLite — it receives everything it
needs as arguments, so the unit tests never touch a database.

## `infrastructure/health_checks.py`

- `check_qdrant()` — reuses `domain/tools/search.py`'s `_get_qdrant_client()` + `get_collections()` (same
  call `/health` already makes).
- `check_openai()` — a **metadata-only** call (`client.models.retrieve(settings.llm.model_name)`), not a
  completion — costs no tokens, satisfies the spec's latency/cost budget.
- `check_telegram_heartbeat(store)` — reads `heartbeat.last_seen_at` from `control_store`.

All three return the same shape: `{status, latency_ms, detail}` — interchangeable, same contract `search.py`
tools already follow.

## `infrastructure/alerts/watchdog.py`

`asyncio.create_task` at API startup, same pattern as the existing `_cleanup_rate_limits` task in `main.py`.
Loop body:

1. Run the three `health_checks.*`, upsert `health_snapshot` (always — dashboard freshness doesn't depend on
   the switch state).
2. `logging.aggregate_usage(since=start_of_today)` → `cost_today_usd`.
3. If `switch.enabled` is `False`: stop here — already in the safe state, nothing to evaluate or spam.
4. `control.evaluate_thresholds(...)`. If a breach and `thresholds.auto_disable_enabled`: disable the
   switch, append the `alert_log` row, send the email. Email failure never blocks the disable — it's
   best-effort and logged as `email_sent: false` (per spec's Failure modes).
5. `logger.info(...)` every cycle, even a no-op one, so "is the watchdog alive" is answerable from logs.

## `infrastructure/api/routers/admin.py`

- `require_admin_token` — a `Depends()` reading `X-Admin-Token`, compared with `hmac.compare_digest` against
  `settings.admin.token`. `401` on mismatch, never logs the token itself.
- `GET /admin/status` — reads `control_store` (switch, thresholds, health_snapshot, alert_log) +
  `logging.aggregate_usage()` (today + month, categories, cache hit rate, requests). No live external calls
  in this path — everything it reads was already written by the watchdog or the interaction log, which is
  what keeps its p95 under the spec's 800ms budget.
- `POST /admin/switch` — writes `switch`; if `enabled=true`, also resolves open `alert_log` rows (see
  Resolution rule above).
- `POST /admin/thresholds` — Pydantic-validated write to `thresholds`.
- `POST /admin/heartbeat` — called by the Telegram bot; upserts `heartbeat.last_seen_at`. Reuses
  `ADMIN_TOKEN` as the internal service-to-service secret (no second credential to manage).
- `POST /admin/test-alert` — calls `alerts.email.send_alert()` directly and appends a `test_alert` /
  `status=resolved` row immediately; never touches the switch.

## `domain/agent.py` / `domain/state.py` changes

`ChatOpenAI` (LangChain) responses carry `response_metadata["token_usage"]` /
`usage_metadata` on the `AIMessage`. In `_run_react_loop` and `_classify_intent`, read that off each LLM
`invoke()` call, sum across the turn's calls (classification + however many ReAct iterations), and set
`tokens_in` / `tokens_out` on the returned dict. `cost_usd = tokens_in * pricing.input_per_1m / 1_000_000 +
tokens_out * pricing.output_per_1m / 1_000_000`, computed once in `run()` before `_update_memory` /
`InteractionLogger.log_interaction`. Missing `usage_metadata` (SDK quirk) → `0`, never an exception — cost
tracking must never be why a turn fails.

## Config additions (`config/base.yaml` + `config.py`)

```yaml
admin:
  # ADMIN_TOKEN env var only — never a plaintext default in yaml

pricing:
  input_per_1m_usd: 0.15   # gpt-4o-mini list price at time of writing — not hardcoded in code
  output_per_1m_usd: 0.60

alerts:
  interval_seconds: 60
  daily_cost_limit_usd: 5.0
  monthly_budget_usd: 120.0
  health_grace_checks: 3
  auto_disable_enabled: true
  email_to: ""
  smtp_host: ""
  smtp_port: 587
  smtp_user: ""
  smtp_from: "control-center@habitantes-grenoble.app"
  # SMTP_PASSWORD env var only
```

`AdminConfig`, `PricingConfig`, `AlertsConfig` added to `config.py` the same way `TelegramConfig` /
`LLMConfig` already read secrets from env via `Field(alias=...)`. `app/telegram_bot.py` already calls
`load_settings()` for `TelegramConfig` — it reads `settings.admin.token` for the heartbeat call with no new
import path.

## Reuse (no change to these files)

- `domain/tools/search.py` (`_get_qdrant_client`) — reused by `health_checks.check_qdrant`.
- `infrastructure/api/routers/health.py` — untouched, stays the cheap Docker liveness probe.
- `infrastructure/api/main.py`'s existing `_cleanup_rate_limits` task pattern — `watchdog.py`'s loop follows
  the same `asyncio.create_task` shape, nothing new introduced at the framework level.
