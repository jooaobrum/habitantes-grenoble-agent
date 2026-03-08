import logging
import uuid
from fastapi import APIRouter, Request
from habitantes.domain.schemas import ChatRequest, ChatResponse, Source
from habitantes.domain.agent import run

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def post_chat(chat_request: ChatRequest, request: Request):
    """Execute one agent turn end-to-end and returned synthesized answer."""
    # Use trace_id injected by middleware
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))

    logger.info(
        "Chat request: chat_id=%s, message_id=%s, trace_id=%s",
        chat_request.chat_id,
        chat_request.message_id,
        trace_id,
    )

    result = run(
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

    return ChatResponse(
        answer=result.get("answer", ""),
        sources=sources,
        intent=result.get("intent", ""),
        category=result.get("category"),
        confidence=result.get("confidence", 0.0),
        trace_id=trace_id,
    )
