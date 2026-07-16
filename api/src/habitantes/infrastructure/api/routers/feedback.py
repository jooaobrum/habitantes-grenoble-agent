import logging
from fastapi import APIRouter, Request
from habitantes.domain.schemas import FeedbackRequest, FeedbackResponse
from habitantes.infrastructure.logging import get_feedback_logger

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
async def post_feedback(feedback_request: FeedbackRequest, request: Request):
    """Persist user feedback as one JSONL line on the mounted log volume."""
    trace_id = getattr(request.state, "trace_id", "no-trace")
    get_feedback_logger().log_feedback(
        chat_id=feedback_request.chat_id,
        message_id=feedback_request.message_id,
        rating=feedback_request.rating,
        trace_id=trace_id,
    )
    logger.info(
        "Feedback received: chat_id=%s, message_id=%s, rating=%s, trace_id=%s",
        feedback_request.chat_id,
        feedback_request.message_id,
        feedback_request.rating,
        trace_id,
    )
    return FeedbackResponse(status="ok")
