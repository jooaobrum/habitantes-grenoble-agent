# Control Center — Tasks

Atomic tasks. Implement one at a time; `pytest tests/ -v` stays green after each. See
[spec.md](spec.md) / [design.md](design.md).

## Phase 1 — Foundation (store + pure logic, no API yet)

- **T1 · Control store** — `infrastructure/control_store.py`: SQLite schema + `init_db`, singleton
  `get_switch`/`set_switch`, singleton `get_thresholds`/`set_thresholds`, `append_alert`/`resolve_open_alerts`,
  `write_health_snapshot`/`read_health_snapshot`, `touch_heartbeat`/`read_heartbeat`.
  *Done when:* unit test creates a db, reads default switch/thresholds, transitions switch state, appends and
  resolves alert rows, upserts a health snapshot and reads back `consecutive_failures`.

- **T2 · Threshold evaluation** — `domain/control.py`: `evaluate_thresholds(cost_today_usd, service_streaks,
  thresholds) -> BreachResult | None`, pure, no I/O. Cost checked before health (spec: more urgent for a
  community bot).
  *Done when:* unit tests cover: under both limits → `None`; cost over limit → cost breach; a service streak
  ≥ `health_grace_checks` → health breach naming that service; `auto_disable_enabled=False` still returns the
  breach (the caller decides whether to act on it, per single-responsibility — evaluation ≠ action).

- **T3 · Config** — `AdminConfig` (`token` ← `ADMIN_TOKEN` env), `PricingConfig`
  (`input_per_1m_usd`/`output_per_1m_usd`), `AlertsConfig` (interval, daily limit, monthly budget display
  value, grace checks, auto-disable flag, email/SMTP fields) added to `config.py`; matching `admin:` /
  `pricing:` / `alerts:` blocks in `config/base.yaml`. `SMTP_PASSWORD` env-only, never in yaml.
  *Done when:* `load_settings().alerts.daily_cost_limit_usd` etc. resolve; missing `ADMIN_TOKEN` is loud
  (fails at startup, not at first admin request).

## Phase 2 — Cost capture on the existing chat path

- **T4 · Token capture** — `state.py`: add `tokens_in: int`, `tokens_out: int`, `cost_usd: float`.
  `agent.py`: read `usage_metadata` off each `_get_llm().invoke()` call in `_classify_intent` and
  `_run_react_loop`, sum per turn, compute `cost_usd` from `settings.pricing` in `run()`. Missing usage →
  `0`, never raises.
  *Done when:* a unit test with a mocked LLM response carrying `usage_metadata` asserts the returned state
  has correct `tokens_in`/`tokens_out`/`cost_usd`; a mocked response *without* usage metadata returns `0`s,
  turn still succeeds. `pytest tests/ -v` stays green (no regression on existing agent tests).

- **T5 · Interaction log + aggregation** — `infrastructure/logging.py`: `InteractionLogger.log_interaction`
  writes `tokens_in`/`tokens_out`/`cost_usd`; add `aggregate_usage(since: datetime) ->
  UsageSummary(requests, cache_hits, cost_usd, categories: dict[str,int], p50_ms, p95_ms)` reading
  `logs/interactions.jsonl`, tolerant of older lines missing the new fields (treat as `0`).
  *Done when:* unit test with a fixture JSONL (mix of old-format and new-format lines) returns correct
  aggregates; a query for "since tomorrow" returns all-zero, not an error.

## Phase 3 — Health probes, email, watchdog

- **T6 · Health probes** — `infrastructure/health_checks.py`: `check_qdrant()` (reuses
  `domain/tools/search.py::_get_qdrant_client`), `check_openai()` (metadata-only `models.retrieve`, no
  completion — zero token cost), `check_telegram_heartbeat(store)`. Same `{status, latency_ms, detail}`
  return shape for all three.
  *Done when:* unit tests mock each client/store and assert `ok`/`unreachable`/`critical` map correctly;
  `check_openai` is asserted to never call a completion endpoint (mock asserts `models.retrieve` only).

- **T7 · Email sender** — `infrastructure/alerts/email.py`: `send_alert(subject, body) -> bool` via stdlib
  `smtplib`, config from `settings.alerts`. Catches connection/auth errors, returns `False`, never raises.
  *Done when:* unit test with a mocked SMTP connection asserts a well-formed message is sent; a connection
  error returns `False` without raising.

- **T8 · Watchdog loop** — `infrastructure/alerts/watchdog.py`: the cycle described in design.md (probe →
  snapshot → aggregate cost → evaluate → act, skipping evaluation entirely when the switch is already off).
  Started via `asyncio.create_task` in `main.py`'s startup event, next to the existing rate-limit cleanup
  task.
  *Done when:* a test drives one cycle with mocked probes/store/email and asserts: (a) snapshot always
  written; (b) no alert/email when under both limits; (c) exactly one `alert_log` row + one email attempt on
  a breach, and the switch flips off; (d) a second cycle with the switch still off does not re-alert or
  re-email (edge-triggered).

## Phase 4 — Admin API + chat gate

- **T9 · Schemas** — `domain/schemas.py`: `AdminStatusResponse`, `SwitchRequest`/`SwitchResponse`,
  `ThresholdsRequest`, `HeartbeatRequest`, `TestAlertResponse` per the spec's Data contracts.
  *Done when:* Pydantic rejects a negative `daily_cost_limit_usd` and an invalid `email_to` with a
  field-level `422`.

- **T10 · Admin router** — `infrastructure/api/routers/admin.py`: `require_admin_token` dependency
  (`hmac.compare_digest`, `401` on mismatch, never logs the token); `GET /admin/status`, `POST
  /admin/switch` (resolves open alerts on `enabled=true`), `POST /admin/thresholds`, `POST
  /admin/heartbeat`, `POST /admin/test-alert`.
  *Done when:* integration tests hit each route with a wrong/missing token → `401`, no state change; a
  correct token exercises the full read/write path against a temp SQLite db.

- **T11 · Chat gate + wiring** — `chat.py`: check `control_store.is_enabled()` (in-process 5s-TTL cache)
  before `run_agent`; disabled → structured `{error_code: "BOT_DISABLED", message, retryable: true}`
  response, no OpenAI/Qdrant call. `main.py`: mount the admin router, mount `app/admin/` as static files at
  `/admin/ui`, start the watchdog task.
  *Done when:* integration test disables the switch, then posts to `/chat/` and asserts the structured
  response with no LLM/Qdrant mock ever invoked; re-enabling restores normal `/chat/` behavior.

## Phase 5 — Frontend + Telegram heartbeat

- **T12 · Wire the dashboard** — `app/admin/index.html`: replace the mockup's static numbers with
  `fetch("/admin/status", {headers: {"X-Admin-Token": ...}})` on load and every 30s; the switch and
  threshold form `POST` on change; a simple token prompt (stored in `localStorage`) replaces hardcoded auth.
  *Done when:* manually opening `/admin/ui/` against a running `make up` stack shows real switch state, real
  service health, and toggling the switch is reflected in a subsequent `/chat/` call within the spec's 5s
  target.

- **T13 · Telegram heartbeat** — `app/telegram_bot.py`: `asyncio.create_task` alongside the existing
  `_cleanup_processed_messages`, posting `POST /admin/heartbeat` every ~30s with `settings.admin.token`.
  *Done when:* running the bot locally against the API shows `telegram_bot` as `ok` in `/admin/status`;
  stopping the bot flips it to `critical` after the staleness window in `health_checks.py`.

## Phase 6 — Hardening, tests, docs

- **T14 · Fail-open verification** — integration test: corrupt/lock the control db, assert `/chat/` still
  answers normally and `/admin/status` reports `control_store: critical`.
  *Done when:* test passes; no chat-path exception is possible from a control-store failure.

- **T15 · Docs** — one section in `docs/ARCHITECTURE.md` (the watchdog + control store, matching
  `.specs/control-center/design.md`), `.gitignore` entry for `artifacts/control/`, `ADMIN_TOKEN` /
  `SMTP_PASSWORD` added to `.env.example`.
  *Done when:* a new engineer can find the control-center flow from `docs/ARCHITECTURE.md` alone.

## Verification (end-to-end)

1. `make up` — no new container appears; `api` logs show the watchdog cycling every `alerts.interval_seconds`.
2. Open `/admin/ui/`, enter the admin token → real switch/health/cost/categories render.
3. Ask the bot a question via Telegram → `/admin/status` cost-today ticks up by a plausible amount.
4. Flip the switch off from the dashboard → the bot replies with the disabled message within 5s, no OpenAI
   call in the logs.
5. Set `daily_cost_limit_usd` to something already exceeded, wait one watchdog interval → switch auto-flips
   off, an email arrives, an `alert_log` row appears with `action=switch_disabled`.
6. Turn the switch back on → the alert row flips to `resolved`.
7. `pytest tests/ -v` and `python tests/eval/run_eval.py` both green (no regression on the existing agent).
