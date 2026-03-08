import logging
from fastapi import APIRouter, Request
from habitantes.domain.schemas import FeedbackRequest, FeedbackResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
async def post_feedback(feedback_request: FeedbackRequest, request: Request):
    """Log user feedback."""
    trace_id = getattr(request.state, "trace_id", "no-trace")
    logger.info(
        "Feedback received: chat_id=%s, message_id=%s, rating=%s, trace_id=%s",
        feedback_request.chat_id,
        feedback_request.message_id,
        feedback_request.rating,
        trace_id,
    )
    # Simple OK response as per design.md. Integration with DB or external log
    # would happen here if required in the future.
    return FeedbackResponse(status="ok")
