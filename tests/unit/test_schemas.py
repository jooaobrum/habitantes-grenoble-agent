import pytest
from pydantic import ValidationError

from habitantes.domain.schemas import (
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    FeedbackResponse,
    HealthResponse,
    Source,
    SwitchRequest,
    ThresholdsRequest,
)
from habitantes.domain.state import AgentState


class TestAgentStateImport:
    def test_agent_state_is_importable(self):
        assert AgentState is not None

    def test_agent_state_fields(self):
        keys = AgentState.__annotations__.keys()
        expected = {
            "chat_id",
            "message",
            "message_id",
            "trace_id",
            "intent",
            "category",
            "context_chunks",
            "answer",
            "sources",
            "confidence",
            "history",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "timings",
            "cached",
            "error",
        }
        assert expected == set(keys)


class TestChatRequest:
    def test_valid(self):
        req = ChatRequest(chat_id="c1", message="Olá", message_id="m1")
        assert req.chat_id == "c1"
        assert req.message == "Olá"

    def test_message_too_short(self):
        with pytest.raises(ValidationError):
            ChatRequest(chat_id="c1", message="", message_id="m1")

    def test_message_too_long(self):
        with pytest.raises(ValidationError):
            ChatRequest(chat_id="c1", message="x" * 2001, message_id="m1")


class TestSource:
    def test_valid(self):
        src = Source(text_snippet="some text", date="2024-01-01", category="visa")
        assert src.category == "visa"


class TestChatResponse:
    def test_valid(self):
        src = Source(text_snippet="text", date="2024-01-01", category="housing")
        resp = ChatResponse(
            answer="Resposta",
            sources=[src],
            intent="qa",
            category="housing",
            confidence=0.9,
            trace_id="trace-123",
        )
        assert resp.intent == "qa"
        assert resp.category == "housing"
        assert len(resp.sources) == 1

    def test_category_none(self):
        resp = ChatResponse(
            answer="Olá!",
            sources=[],
            intent="greeting",
            category=None,
            confidence=1.0,
            trace_id="trace-456",
        )
        assert resp.category is None


class TestFeedbackRequest:
    def test_valid_up(self):
        req = FeedbackRequest(chat_id="c1", message_id="m1", rating="up")
        assert req.rating == "up"

    def test_valid_down(self):
        req = FeedbackRequest(chat_id="c1", message_id="m1", rating="down")
        assert req.rating == "down"

    def test_invalid_rating(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(chat_id="c1", message_id="m1", rating="neutral")


class TestFeedbackResponse:
    def test_valid(self):
        resp = FeedbackResponse(status="ok")
        assert resp.status == "ok"


class TestHealthResponse:
    def test_valid(self):
        resp = HealthResponse(status="healthy", qdrant="connected", version="0.1.0")
        assert resp.status == "healthy"
        assert resp.qdrant == "connected"


class TestSwitchRequest:
    def test_valid(self):
        assert SwitchRequest(enabled=False).enabled is False


class TestThresholdsRequest:
    def test_valid(self):
        req = ThresholdsRequest(
            daily_cost_limit_usd=5.0,
            health_grace_checks=3,
            email_to="ops@example.com",
            auto_disable_enabled=True,
        )
        assert req.daily_cost_limit_usd == 5.0
        assert req.email_to == "ops@example.com"

    def test_empty_email_allowed(self):
        req = ThresholdsRequest(
            daily_cost_limit_usd=5.0,
            health_grace_checks=3,
            email_to="",
            auto_disable_enabled=True,
        )
        assert req.email_to == ""

    def test_negative_cost_rejected(self):
        with pytest.raises(ValidationError):
            ThresholdsRequest(
                daily_cost_limit_usd=-1.0,
                health_grace_checks=3,
                email_to="ops@example.com",
                auto_disable_enabled=True,
            )

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            ThresholdsRequest(
                daily_cost_limit_usd=5.0,
                health_grace_checks=3,
                email_to="not-an-email",
                auto_disable_enabled=True,
            )

    def test_zero_grace_checks_rejected(self):
        with pytest.raises(ValidationError):
            ThresholdsRequest(
                daily_cost_limit_usd=5.0,
                health_grace_checks=0,
                email_to="ops@example.com",
                auto_disable_enabled=True,
            )
