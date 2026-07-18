import asyncio
import logging
import uuid
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from habitantes.domain import (
    ChatRequest,
    ChatResponse,
    Source,
    reset_agent_memory,
    run_agent,
)
from habitantes.domain.schemas import ResetRequest, ResetResponse
from habitantes.infrastructure import control_store
from habitantes.infrastructure.logging import get_interaction_logger

logger = logging.getLogger(__name__)

router = APIRouter()

_DISABLED_MESSAGE = (
    "O assistente está temporariamente indisponível. " "Tente novamente mais tarde."
)


@router.post("/", response_model=ChatResponse)
async def post_chat(chat_request: ChatRequest, request: Request):
    """Execute one agent turn end-to-end and returned synthesized answer."""
    # Use trace_id injected by middleware
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))

    # Kill switch: gate before any OpenAI/Qdrant work (cached 5s read).
    if not control_store.is_enabled():
        logger.info("Chat blocked: bot disabled, trace_id=%s", trace_id)
        return JSONResponse(
            status_code=200,
            content={
                "error_code": "BOT_DISABLED",
                "message": _DISABLED_MESSAGE,
                "retryable": True,
                "answer": _DISABLED_MESSAGE,
                "trace_id": trace_id,
            },
        )

    logger.info(
        "Chat request: chat_id=%s, message_id=%s, trace_id=%s",
        chat_request.chat_id,
        chat_request.message_id,
        trace_id,
    )

    result = await asyncio.to_thread(
        run_agent,
        chat_id=chat_request.chat_id,
        message=chat_request.message,
        message_id=chat_request.message_id,
        trace_id=trace_id,
    )

    sources = [
        Source(
            text_snippet=s.get("text_snippet", ""),
            date=s.get("date", ""),
            category=s.get("category", ""),
        )
        for s in result.get("sources", [])
    ]

    # Log interaction for traceability
    try:
        get_interaction_logger().log_interaction(result)
    except Exception as e:
        logger.error(f"Failed to log interaction: {e}")

    return ChatResponse(
        answer=result.get("answer", ""),
        sources=sources,
        intent=result.get("intent", ""),
        category=result.get("category"),
        confidence=result.get("confidence", 0.0),
        trace_id=trace_id,
        cached=result.get("cached", False),
    )


@router.post("/reset", response_model=ResetResponse)
async def post_reset(reset_request: ResetRequest, request: Request):
    """Clear a chat's short-term memory (history + selected category).

    Not gated by the kill switch — it's a local, no-cost housekeeping action
    (no LLM/Qdrant call), unlike /chat/ which does real inference work.
    """
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    reset_agent_memory(reset_request.chat_id)
    logger.info(
        "Memory reset: chat_id=%s, trace_id=%s", reset_request.chat_id, trace_id
    )
    return ResetResponse(status="ok")
