"""Intent classification prompt.

Classifies user messages into: greeting | qa | feedback | out_of_scope.
Returns a list of OpenAI-style message dicts ready for chat completions.
"""

_SYSTEM = """\
You are an intent classifier for a Telegram chatbot that helps Brazilian expats in Grenoble, France.

Classify the user's message into EXACTLY one of the following intents:

- greeting     : The user is greeting the bot (e.g., "Oi", "Olá", "Bom dia", "Boa noite", "Tudo bem?")
- qa           : The user is asking a question about Grenoble or expat life there. This includes
                 both experiential/community topics (visa, housing, healthcare, banking, transport,
                 education, CAF, etc.) AND factual/generalist/current questions about Grenoble
                 (e.g., number of inhabitants, current events, weather, official procedures,
                 landmarks). If the question is genuinely about Grenoble, classify it as qa.
- feedback     : The user is giving positive or negative feedback about a previous answer (e.g., "👍", "👎", "Obrigado", "Não me ajudou", "Perfeito!")
- out_of_scope : The user is sending a message NOT about Grenoble (e.g., other cities or countries,
                 general world knowledge unrelated to Grenoble, small talk beyond greetings)

Rules:
- Respond ONLY with valid JSON. No explanation, no markdown, no extra text.
- Use ONLY the exact intent values listed above.

Output format:
{"intent": "<intent>"}
"""


def build_intent_messages(
    message: str,
    history: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Return messages list for intent classification.

    Args:
        message: The user's current message.
        history: Optional last N conversation turns [{role, content}].

    Returns:
        List of message dicts for OpenAI chat completions.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]

    if history:
        for turn in history:
            messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": message})
    return messages
