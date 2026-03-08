from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from habitantes.infrastructure.api.main import app

client = TestClient(app)


def test_health_success():
    """Test /health endpoint when Qdrant is connected."""
    with patch(
        "habitantes.infrastructure.api.routers.health._get_qdrant_client"
    ) as mock_client:
        mock_qdrant = MagicMock()
        mock_client.return_value = mock_qdrant

        response = client.get("/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["qdrant"] == "connected"
        assert "version" in data


def test_health_qdrant_unreachable():
    """Test /health endpoint when Qdrant is unreachable."""
    with patch(
        "habitantes.infrastructure.api.routers.health._get_qdrant_client"
    ) as mock_client:
        mock_client.side_effect = Exception("Connection error")

        response = client.get("/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["qdrant"] == "unreachable"


def test_feedback_success():
    """Test /feedback endpoint."""
    feedback_data = {"chat_id": "123456", "message_id": "msg_001", "rating": "up"}
    response = client.post("/feedback/", json=feedback_data)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_success():
    """Test /chat endpoint with mocked agent run."""
    chat_request = {
        "chat_id": "123456",
        "message": "Como conseguir um visto?",
        "message_id": "msg_002",
    }

    mock_result = {
        "answer": "Você precisa de um visto tipo D.",
        "sources": [
            {
                "text_snippet": "visto tipo D info",
                "date": "2023-01-01",
                "category": "Visa",
            }
        ],
        "intent": "qa",
        "category": "Visa & Residency",
        "confidence": 0.9,
    }

    with patch("habitantes.infrastructure.api.routers.chat.run") as mock_run:
        mock_run.return_value = mock_result

        response = client.post("/chat/", json=chat_request)
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == mock_result["answer"]
        assert len(data["sources"]) == 1
        assert data["intent"] == "qa"
        assert "trace_id" in data
        assert response.headers.get("X-Trace-Id") == data["trace_id"]


def test_rate_limiting():
    """Test rate limiting middleware."""
    chat_id = "blocked_user"
    headers = {"X-Chat-Id": chat_id}

    # Send 100 requests (limit is 100)
    for _ in range(100):
        client.post(
            "/feedback/",
            json={"chat_id": chat_id, "message_id": "id", "rating": "up"},
            headers=headers,
        )

    # The 101st should be blocked
    response = client.post(
        "/feedback/",
        json={"chat_id": chat_id, "message_id": "id", "rating": "up"},
        headers=headers,
    )
    assert response.status_code == 429
    assert (
        response.json()["detail"]
        == "Too many requests. Limit is 100 per hour per user."
    )
