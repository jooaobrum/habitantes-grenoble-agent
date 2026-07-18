from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from habitantes.domain import agent as agent_mod
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


def test_reset_success():
    """Test /chat/reset actually clears the chat's agent-side memory."""
    chat_id = "reset-endpoint-test"
    agent_mod._update_memory(
        chat_id,
        user_message="Oi",
        assistant_answer="Olá!",
        category="Banking & Finance",
        intent="qa",
    )
    assert agent_mod._get_history(chat_id) != []

    response = client.post("/chat/reset", json={"chat_id": chat_id})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert agent_mod._get_history(chat_id) == []
    assert agent_mod._get_selected_category(chat_id) == ""


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
