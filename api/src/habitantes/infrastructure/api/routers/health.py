from fastapi import APIRouter
from habitantes.domain.schemas import HealthResponse
from habitantes.domain.tools import _get_qdrant_client

router = APIRouter()


@router.get("/", response_model=HealthResponse)
async def get_health():
    """Check health and connectivity to external services."""
    qdrant_status = "connected"
    try:
        client = _get_qdrant_client()
        # Simple check for connectivity
        client.get_collections()
    except Exception:
        qdrant_status = "unreachable"

    return HealthResponse(status="healthy", qdrant=qdrant_status, version="0.1.0")
