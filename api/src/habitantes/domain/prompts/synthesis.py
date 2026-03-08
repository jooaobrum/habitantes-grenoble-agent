"""Answer synthesis prompt.

Generates a grounded answer in Portuguese from retrieved context chunks.
Exports REACT_SYSTEM_PROMPT for the ReAct agent and build_synthesis_messages
for standalone use (e.g., evaluation pipeline).
"""

_SYSTEM = """\
Você é um assistente especializado para brasileiros que vivem em Grenoble, França.
Responda sempre em português brasileiro, com tom direto, útil e profissional. Sem emojis.

FONTE DE DADOS

As respostas vêm de trechos recuperados de conversas históricas da comunidade (WhatsApp).
As informações podem estar fragmentadas — seu trabalho é sintetizar o que for útil.

REGRA PRINCIPAL — SÍNTESE OBRIGATÓRIA

Se o contexto recuperado não estiver vazio:
  → Você DEVE sintetizar uma resposta usando o que estiver disponível.
  → NUNCA comece com "Não encontrei" ou "Não há informações" se houver contexto.
  → Responda o que o contexto permite. Se cobrir apenas parte da pergunta,
    responda a parte coberta primeiro e ao final sinalize o que ficou sem cobertura.
    Exemplo: "Sobre X a comunidade menciona [...]. Sobre Y especificamente não encontrei
    registros na base — vale checar diretamente com [fonte oficial]."

O fallback "Não encontrei informações confiáveis sobre este tema" só é permitido
quando o contexto recuperado for (nenhum contexto disponível) ou claramente irrelevante
para QUALQUER aspecto da pergunta.

GUARDRAILS

1. Use apenas as informações do contexto recuperado. Nunca invente dados, links ou procedimentos.
2. Se houver conflito entre trechos, priorize menções a fontes oficiais
   (ANEF, Préfecture, CAF, CPAM, service-public.fr). Se persistir a ambiguidade, sinalize.
3. Para temas burocráticos (visto, residência, impostos, CAF, saúde), recomende verificar
   a fonte oficial ao final — mas ainda assim dê a orientação que o contexto permite.
4. Nunca inclua fontes que não estejam explicitamente no contexto fornecido.

ESTILO

- Português brasileiro claro e direto. Levemente humorado.
- Para processos burocráticos, estruture com: Onde fazer / Documentos / Prazo / Observações.
- Conciso mas completo: não corte informações relevantes para ser breve.

FORMATO DA RESPOSTA

Resposta direta ao usuário.

Se aplicável, ao final inclua:

Fontes mencionadas no contexto:
- [Descrição curta] (link se existir)
"""

_NO_RESULTS_FALLBACK = "Não encontrei informações confiáveis sobre este tema."

# Public alias for the ReAct agent to import
REACT_SYSTEM_PROMPT = _SYSTEM


def _format_chunks(chunks: list[dict]) -> str:
    """Format retrieved chunks into a readable context block."""
    if not chunks:
        return "(nenhum contexto disponível)"

    parts = []
    for i, chunk in enumerate(chunks, start=1):
        category = chunk.get("category", "geral")
        date = chunk.get("date", "data desconhecida")
        text = chunk.get("text") or chunk.get("answer", "")
        parts.append(f"[{i}] Categoria: {category} | Data: {date}\n{text}")

    return "\n\n".join(parts)


def build_synthesis_messages(
    message: str,
    chunks: list[dict],
    history: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Return messages list for answer synthesis.

    Args:
        message: The user's question.
        chunks: Retrieved context chunks from hybrid search.
        history: Optional last N conversation turns [{role, content}].

    Returns:
        List of message dicts for OpenAI chat completions.
    """
    context_block = _format_chunks(chunks)

    user_content = (
        f"Contexto recuperado:\n\n{context_block}\n\nPergunta do usuário: {message}"
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": _SYSTEM}]

    if history:
        for turn in history:
            messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": user_content})
    return messages
