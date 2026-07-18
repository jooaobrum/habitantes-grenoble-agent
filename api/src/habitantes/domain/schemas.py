import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ChatRequest(BaseModel):
    chat_id: str
    message: str = Field(min_length=1, max_length=2000)
    message_id: str


class Source(BaseModel):
    text_snippet: str
    date: str
    category: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    intent: str
    category: str | None
    confidence: float
    trace_id: str
    cached: bool = False


class FeedbackRequest(BaseModel):
    chat_id: str
    message_id: str
    rating: Literal["up", "down"]


class FeedbackResponse(BaseModel):
    status: str  # "ok"


class ResetRequest(BaseModel):
    chat_id: str


class ResetResponse(BaseModel):
    status: str  # "ok"


class IntentClassification(BaseModel):
    """Structured-output contract for Layer 1 intent classification.

    Bound to the LLM via `.with_structured_output()` so the provider's native
    function-calling / JSON-schema mode enforces this shape — no brittle
    `json.loads` on free-form model text.
    """

    intent: Literal["greeting", "qa", "feedback", "out_of_scope"]


class HealthResponse(BaseModel):
    status: str  # "healthy"
    qdrant: str  # "connected" | "unreachable"
    version: str  # "0.1.0"


# ── Control Center — admin contracts ─────────────────────────────────────────


class SwitchStatus(BaseModel):
    enabled: bool
    changed_at: str


class ServiceStatus(BaseModel):
    name: str
    status: str  # "ok" | "degraded" | "critical" | "unreachable"
    latency_ms: float | None
    checked_at: str


class Kpis(BaseModel):
    requests_today: int
    cache_hit_rate: float
    cost_today_usd: float
    cost_month_usd: float
    budget_daily_usd: float
    budget_monthly_usd: float
    uptime_24h_pct: float


class CategoryCount(BaseModel):
    name: str
    count: int


class CostSeriesPoint(BaseModel):
    date: str  # YYYY-MM-DD
    requests: int
    cost_usd: float


class ThresholdsState(BaseModel):
    daily_cost_limit_usd: float
    health_grace_checks: int
    email_to: str
    auto_disable_enabled: bool
    monthly_budget_usd: float


class AlertEntry(BaseModel):
    timestamp: str
    trigger: str
    measured: str | None = None
    action: str
    status: str


class AdminStatusResponse(BaseModel):
    switch: SwitchStatus
    services: list[ServiceStatus]
    kpis: Kpis
    categories: list[CategoryCount]
    cost_series: list[CostSeriesPoint]
    thresholds: ThresholdsState
    alerts: list[AlertEntry]


class SwitchRequest(BaseModel):
    enabled: bool


class SwitchResponse(BaseModel):
    enabled: bool
    changed_at: str


class ThresholdsRequest(BaseModel):
    daily_cost_limit_usd: float = Field(gt=0)
    health_grace_checks: int = Field(ge=1)
    email_to: str
    auto_disable_enabled: bool

    @field_validator("email_to")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        # Empty string means "alerts unaddressed" (config default) — allowed;
        # any non-empty value must look like an email.
        if v and not _EMAIL_RE.match(v):
            raise ValueError("email_to must be a valid email address or empty")
        return v


class HeartbeatRequest(BaseModel):
    service: str = "telegram_bot"


class TestAlertResponse(BaseModel):
    email_sent: bool
    detail: str
