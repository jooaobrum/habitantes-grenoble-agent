"""Unit tests for the agent's in-process short-term memory (agent.py)."""

from habitantes.domain import agent as agent_mod


def test_update_then_reset_clears_history_and_category():
    chat_id = "test-chat-reset-1"

    agent_mod._update_memory(
        chat_id,
        user_message="Oi",
        assistant_answer="Olá!",
        category="Visa & Residency",
        intent="qa",
    )
    assert agent_mod._get_history(chat_id) == [
        {"role": "user", "content": "Oi"},
        {"role": "assistant", "content": "Olá!"},
    ]
    assert agent_mod._get_selected_category(chat_id) == "Visa & Residency"

    agent_mod.reset_memory(chat_id)

    assert agent_mod._get_history(chat_id) == []
    assert agent_mod._get_selected_category(chat_id) == ""


def test_reset_is_idempotent_on_unknown_chat_id():
    # Never touched — reset must not raise.
    agent_mod.reset_memory("never-seen-chat-id")
    assert agent_mod._get_history("never-seen-chat-id") == []
