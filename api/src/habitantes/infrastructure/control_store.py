"""SQLite persistence for the Control Center — pure I/O, no decisions.

Holds the kill switch, editable thresholds, the alert log, per-service health
snapshots, and the Telegram bot heartbeat. Thin wrapper: the decision of whether
a threshold is breached lives in `domain/control.py`, not here.

Every public function takes an optional `db_path` so tests can point at a
throwaway database; production callers rely on the default under `artifacts/`.
"""

import datetime
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from habitantes.config import load_settings

logger = logging.getLogger(__name__)

# Repo root: .../infrastructure/control_store.py -> parents[4] == repo root.
_REPO_ROOT = Path(__file__).parents[4]
DEFAULT_DB_PATH = _REPO_ROOT / "artifacts" / "control" / "control.db"

_SWITCH_ID = 1
_THRESHOLDS_ID = 1


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """Create tables if absent and seed the singleton switch/thresholds rows.

    Idempotent: safe to call on every startup. Threshold defaults come from
    `settings.alerts` so config stays the single source of truth.
    """
    alerts = load_settings().alerts
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS switch (
                id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL,
                changed_at TEXT NOT NULL,
                changed_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS thresholds (
                id INTEGER PRIMARY KEY,
                daily_cost_limit_usd REAL NOT NULL,
                health_grace_checks INTEGER NOT NULL,
                email_to TEXT NOT NULL,
                auto_disable_enabled INTEGER NOT NULL,
                monthly_budget_usd REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alert_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                trigger TEXT NOT NULL,
                measured TEXT,
                action TEXT NOT NULL,
                email_sent INTEGER,
                status TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS health_snapshot (
                service TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                latency_ms REAL,
                checked_at TEXT NOT NULL,
                detail TEXT,
                consecutive_failures INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS heartbeat (
                service TEXT PRIMARY KEY,
                last_seen_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO switch (id, enabled, changed_at, changed_by)
            VALUES (?, 1, ?, 'default')
            """,
            (_SWITCH_ID, _now()),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO thresholds
                (id, daily_cost_limit_usd, health_grace_checks, email_to,
                 auto_disable_enabled, monthly_budget_usd, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _THRESHOLDS_ID,
                alerts.daily_cost_limit_usd,
                alerts.health_grace_checks,
                alerts.email_to,
                1 if alerts.auto_disable_enabled else 0,
                alerts.monthly_budget_usd,
                _now(),
            ),
        )
        conn.commit()


# ── Switch ───────────────────────────────────────────────────────────────────


def get_switch(db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT enabled, changed_at, changed_by FROM switch WHERE id = ?",
            (_SWITCH_ID,),
        ).fetchone()
    return {
        "enabled": bool(row["enabled"]),
        "changed_at": row["changed_at"],
        "changed_by": row["changed_by"],
    }


def set_switch(
    enabled: bool,
    changed_by: str,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE switch SET enabled = ?, changed_at = ?, changed_by = ? WHERE id = ?",
            (1 if enabled else 0, _now(), changed_by, _SWITCH_ID),
        )
        conn.commit()
    _invalidate_enabled_cache()
    return get_switch(db_path)


# ── Chat-path gate (cached, fail-open) ───────────────────────────────────────

_ENABLED_CACHE_TTL = 5.0  # seconds — spec's "reflected within 5s" budget
_enabled_cache: dict[str, Any] = {"value": None, "expires": 0.0}


def _invalidate_enabled_cache() -> None:
    _enabled_cache["value"] = None
    _enabled_cache["expires"] = 0.0


def is_enabled(db_path: Path | str | None = None) -> bool:
    """Return the kill-switch state for the chat path, cached for 5s.

    Fail-open (spec Safety): if the store can't be read, treat the bot as
    enabled and log — a broken 200KB local file must never take the whole
    community bot down. The failure surfaces separately as a `critical`
    health-snapshot row for the operator.
    """
    now = time.monotonic()
    if _enabled_cache["value"] is not None and now < _enabled_cache["expires"]:
        return _enabled_cache["value"]

    path = db_path if db_path is not None else DEFAULT_DB_PATH
    try:
        enabled = get_switch(path)["enabled"]
    except Exception:
        logger.error(
            "is_enabled: control store unreadable — failing open", exc_info=True
        )
        enabled = True

    _enabled_cache["value"] = enabled
    _enabled_cache["expires"] = now + _ENABLED_CACHE_TTL
    return enabled


# ── Thresholds ───────────────────────────────────────────────────────────────


def get_thresholds(db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any]:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT daily_cost_limit_usd, health_grace_checks, email_to,
                   auto_disable_enabled, monthly_budget_usd, updated_at
            FROM thresholds WHERE id = ?
            """,
            (_THRESHOLDS_ID,),
        ).fetchone()
    return {
        "daily_cost_limit_usd": row["daily_cost_limit_usd"],
        "health_grace_checks": row["health_grace_checks"],
        "email_to": row["email_to"],
        "auto_disable_enabled": bool(row["auto_disable_enabled"]),
        "monthly_budget_usd": row["monthly_budget_usd"],
        "updated_at": row["updated_at"],
    }


def set_thresholds(
    daily_cost_limit_usd: float,
    health_grace_checks: int,
    email_to: str,
    auto_disable_enabled: bool,
    monthly_budget_usd: float,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE thresholds
            SET daily_cost_limit_usd = ?, health_grace_checks = ?, email_to = ?,
                auto_disable_enabled = ?, monthly_budget_usd = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                daily_cost_limit_usd,
                health_grace_checks,
                email_to,
                1 if auto_disable_enabled else 0,
                monthly_budget_usd,
                _now(),
                _THRESHOLDS_ID,
            ),
        )
        conn.commit()
    return get_thresholds(db_path)


# ── Alert log ────────────────────────────────────────────────────────────────


def append_alert(
    trigger: str,
    measured: str | None,
    action: str,
    email_sent: bool | None = None,
    status: str = "active",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    """Append an alert row and return its id."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO alert_log
                (timestamp, trigger, measured, action, email_sent, status, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                _now(),
                trigger,
                measured,
                action,
                None if email_sent is None else (1 if email_sent else 0),
                status,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def resolve_open_alerts(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    """Mark every currently-active alert as resolved; return the count updated."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "UPDATE alert_log SET status = 'resolved', resolved_at = ? WHERE status = 'active'",
            (_now(),),
        )
        conn.commit()
        return cur.rowcount


def read_alerts(
    limit: int = 50, db_path: Path | str = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM alert_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Health snapshot ──────────────────────────────────────────────────────────


def write_health_snapshot(
    service: str,
    status: str,
    latency_ms: float | None,
    consecutive_failures: int,
    detail: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    """Upsert one service's health row. Caller computes `consecutive_failures`."""
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO health_snapshot
                (service, status, latency_ms, checked_at, detail, consecutive_failures)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(service) DO UPDATE SET
                status = excluded.status,
                latency_ms = excluded.latency_ms,
                checked_at = excluded.checked_at,
                detail = excluded.detail,
                consecutive_failures = excluded.consecutive_failures
            """,
            (service, status, latency_ms, _now(), detail, consecutive_failures),
        )
        conn.commit()


def read_health_snapshot(
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM health_snapshot ORDER BY service").fetchall()
    return [dict(r) for r in rows]


# ── Heartbeat ────────────────────────────────────────────────────────────────


def touch_heartbeat(
    service: str = "telegram_bot", db_path: Path | str = DEFAULT_DB_PATH
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO heartbeat (service, last_seen_at) VALUES (?, ?)
            ON CONFLICT(service) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """,
            (service, _now()),
        )
        conn.commit()


def read_heartbeat(
    service: str = "telegram_bot", db_path: Path | str = DEFAULT_DB_PATH
) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT service, last_seen_at FROM heartbeat WHERE service = ?",
            (service,),
        ).fetchone()
    return dict(row) if row else None
