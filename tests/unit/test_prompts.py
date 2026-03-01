from habitantes.domain.prompts.intent import build_intent_messages
from habitantes.domain.prompts.synthesis import build_synthesis_messages


def _assert_valid_messages(messages: list) -> None:
    assert isinstance(messages, list)
    assert len(messages) >= 2
    for msg in messages:
        assert "role" in msg
        assert "content" in msg
        assert msg["role"] in ("system", "user", "assistant")
        assert isinstance(msg["content"], str)
        assert len(msg["content"]) > 0
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"


class TestIntentPrompt:
    def test_basic_render(self):
        msgs = build_intent_messages("Como renovar meu visto?")
        _assert_valid_messages(msgs)

    def test_message_in_output(self):
        msg = "Olá, tudo bem?"
        msgs = build_intent_messages(msg)
        assert msgs[-1]["content"] == msg

    def test_system_contains_intents(self):
        msgs = build_intent_messages("Oi!")
        system_content = msgs[0]["content"]
        for intent in ("greeting", "qa", "feedback", "out_of_scope"):
            assert intent in system_content

    def test_with_history(self):
        history = [
            {"role": "user", "content": "Oi"},
            {"role": "assistant", "content": "Olá! Como posso ajudar?"},
        ]
        msgs = build_intent_messages("Quero saber sobre visto", history=history)
        _assert_valid_messages(msgs)
        # system + 2 history + 1 user
        assert len(msgs) == 4

    def test_without_history(self):
        msgs = build_intent_messages("Teste", history=None)
        # system + user only
        assert len(msgs) == 2


class TestSynthesisPrompt:
    _sample_chunks = [
        {
            "text": "Para renovar o titre de séjour, acesse o site da ANEF.",
            "category": "visa",
            "date": "2024-05-01",
            "score": 0.92,
        },
        {
            "text": "O agendamento pode demorar vários meses.",
            "category": "visa",
            "date": "2024-06-15",
            "score": 0.88,
        },
    ]

    def test_basic_render(self):
        msgs = build_synthesis_messages("Como renovar meu visto?", self._sample_chunks)
        _assert_valid_messages(msgs)

    def test_chunks_in_user_message(self):
        msgs = build_synthesis_messages("Como renovar?", self._sample_chunks)
        user_content = msgs[-1]["content"]
        assert "ANEF" in user_content
        assert "visa" in user_content

    def test_message_in_user_content(self):
        question = "Quero saber sobre transporte público."
        msgs = build_synthesis_messages(question, self._sample_chunks)
        assert question in msgs[-1]["content"]

    def test_empty_chunks_renders_fallback_placeholder(self):
        msgs = build_synthesis_messages("Pergunta sem contexto", chunks=[])
        _assert_valid_messages(msgs)
        assert "nenhum contexto disponível" in msgs[-1]["content"]

    def test_system_in_portuguese(self):
        msgs = build_synthesis_messages("Pergunta", self._sample_chunks)
        system_content = msgs[0]["content"]
        assert "Português brasileiro" in system_content

    def test_with_history(self):
        history = [
            {"role": "user", "content": "Oi"},
            {"role": "assistant", "content": "Olá!"},
        ]
        msgs = build_synthesis_messages(
            "Sobre visto", self._sample_chunks, history=history
        )
        _assert_valid_messages(msgs)
        # system + 2 history + 1 user
        assert len(msgs) == 4

    def test_system_grounding_rule(self):
        msgs = build_synthesis_messages("Pergunta", self._sample_chunks)
        system_content = msgs[0]["content"]
        assert "Não encontrei informação confiável" in system_content
