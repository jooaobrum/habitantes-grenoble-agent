from typing import Literal

from pydantic import BaseModel, Field


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


class FeedbackRequest(BaseModel):
    chat_id: str
    message_id: str
    rating: Literal["up", "down"]


class FeedbackResponse(BaseModel):
    status: str  # "ok"


class HealthResponse(BaseModel):
    status: str  # "healthy"
    qdrant: str  # "connected" | "unreachable"
    version: str  # "0.1.0"
