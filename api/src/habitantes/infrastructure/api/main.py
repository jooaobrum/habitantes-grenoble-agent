import logging
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from habitantes.infrastructure.api.routers import chat, feedback, health

# Simple in-memory rate limiting state
# Reset on restart as per design.md
_rate_limits: dict[str, list[float]] = defaultdict(list)
_MAX_REQ_PER_HOUR = 100
_WINDOW_SECONDS = 3600


def check_rate_limit(chat_id: str) -> bool:
    """Check if the given chat_id has exceeded the rate limit of 100 req/hour."""
    now = time.time()
    # Filter only events in the last hour
    history = [t for t in _rate_limits[chat_id] if now - t < _WINDOW_SECONDS]
    _rate_limits[chat_id] = history

    if len(history) >= _MAX_REQ_PER_HOUR:
        return False

    _rate_limits[chat_id].append(now)
    return True


# Initialize logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Habitantes Grenoble Agent API",
    description="Backend API for the Grenoble Brazilian Expats chatbot.",
    version="0.1.0",
)


@app.middleware("http")
async def api_middleware(request: Request, call_next):
    """Middleware for trace_id propagation and rate limiting."""
    # 1. Trace ID extraction/generation
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    request.state.trace_id = trace_id

    # 2. Rate limiting check
    # Rate limit based on X-Chat-Id header or client host IP
    # In a real app we would use a dependency that reads the body properly,
    # but for now we expect X-Chat-Id for user-level identification.
    user_id = request.headers.get("X-Chat-Id", request.client.host)

    # Simple check for /chat and /feedback endpoints
    path = request.url.path
    if path.startswith(("/chat", "/feedback")):
        if not check_rate_limit(user_id):
            logger.warning(
                "Rate limit exceeded: user_id=%s, trace_id=%s", user_id, trace_id
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Too many requests. Limit is 100 per hour per user.",
                    "trace_id": trace_id,
                },
                headers={"X-Trace-Id": trace_id},
            )

    # 3. Request execution
    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
    except Exception:
        logger.exception("Uncaught exception: trace_id=%s", trace_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal Server Error", "trace_id": trace_id},
            headers={"X-Trace-Id": trace_id},
        )


# Include routers
app.include_router(chat, prefix="/chat", tags=["Agent"])
app.include_router(feedback, prefix="/feedback", tags=["Feedback"])
app.include_router(health, prefix="/health", tags=["Health"])


@app.get("/")
async def root():
    return {"name": "Habitantes Grenoble API", "status": "running"}
