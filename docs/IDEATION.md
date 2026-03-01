# 🔎 Conversation Summary

You are building a knowledge-based chatbot for Brazilian expats in Grenoble, initially deployed to Telegram (WhatsApp later), serving ~300 users with 10–30 concurrent chats.

The system:
- Uses ingestion pipeline from WhatsApp data → QA extraction → classification → filtering
- Uses hybrid retrieval (dense + sparse embeddings)
- Stores in Qdrant
- Uses OpenAI selectively for synthesis
- Requires low-cost, 24/7 availability
- Must handle concurrency safely (idempotency, per-chat locks, no heavy FIFO)
- Should be architected cleanly (orchestration, state, tools separation)
- Target infra: low-cost VPS (~$8–12/month)
- Cost focus: optimize LLM usage, not infra

You are aiming for:
- Production-grade architecture
- Low operational complexity
- Clean agent workflow
- Sustainable cost model


# Ideation Brief


## 1. Problem

Brazilian expats in Grenoble repeatedly ask the same bureaucratic, housing, and daily-life questions in WhatsApp groups. Information exists but is fragmented, informal, outdated, and hard to search. A structured, reliable assistant is needed to centralize and synthesize trusted answers.


## 2. Target Users

- Primary (runs it daily): Brazilian expats in Grenoble using Telegram/WhatsApp
- Top 3 tasks they need to do:
  1. Ask bureaucratic questions (visa, CAF, residency, banking)
  2. Get practical local advice (housing, transport, health)
  3. Find reliable links and official sources quickly


## 3. Golden Path

Your example:

- Input:
  "Como renovar meu titre de séjour passeport talent em Grenoble?"

- Expected output:
  - Clear explanation of renewal steps
  - Required documents
  - ANEF or préfecture link
  - Timeline expectations
  - Confirmation if process changed recently

- Example:

Conseguir um **rendez-vous para retirada do titre de séjour em Grenoble** está realmente complicado no momento.

### Situação atual

- Pode levar **vários meses** para conseguir vaga.
- Há relatos de espera de até **6 meses**.
- A disponibilidade é baixa e a concorrência alta.
- Ir presencialmente quase nunca resolve.
- Contratar advogado normalmente **não acelera** o processo.

---

## Onde fazer o agendamento

Pelo site oficial da ANEF / Préfecture:

https://administration-etrangers-en-france.interieur.gouv.fr/particuliers/#/

---

## Como aumentar suas chances

### 1) Monitorar o site constantemente
As vagas:
- São limitadas.
- Costumam abrir em **horários específicos**, geralmente pela manhã.
- Acabam muito rápido.

Dica relatada:
- Entrar no site **antes das 9h**.
- Atualizar a página exatamente no horário de abertura.
- Alguns mencionam que entre **domingo e segunda-feira** pode haver mais disponibilidade.

---

### 2) Persistência
Infelizmente, não existe método oficial para acelerar o processo.
Quando aparece “aucun créneau disponible”, a única alternativa tem sido continuar tentando.

---

### 3) Buscar associações locais
Como a préfecture raramente responde dúvidas diretamente, algumas pessoas procuram **associações de apoio a imigrantes** para obter orientações atualizadas.

---

## Observação importante

Para questões de visto e residência, sempre confirme no site oficial da ANEF ou da Préfecture, pois regras e funcionamento podem mudar.

Fontes mencionadas no contexto:
- Site oficial ANEF / Administração de Estrangeiros na França
  https://administration-etrangers-en-france.interieur.gouv.fr/particuliers/#/



## 4. Data & Tools

Data Sources:
- WhatsApp historical chat export (Jan 2021 → Feb 2026)
- Extracted QA pairs (JSON per thread)
- Curated and filtered knowledge base

Storage:
- Qdrant (hybrid dense + sparse retrieval)

Models & Tools:
- SentenceTransformers (Portuguese dense embedding)
- BM25 sparse embedding (adapted to portuguese)
- OpenAI for answer synthesis
- MemoryState from langgraph for short-term memory
- Qdrant for long-term memory after summarization (async)
- Telegram Bot API in MVP, possibility to migrate to WhatsApp later


## 5. Success Criteria

- Quality metric: ≥85% of answers rated helpful by users
- Latency target (p95): < 5 seconds


## 6. Constraints

- Data access / compliance: Can use OpenAI API (no strict local-only requirement)
- Runtime: Ultra Low-cost VPS (Hetzner / OVH style)
- Team size: 1 engineer
- Framework familiarity: Python, FastAPI, transformers, Qdrant


## 7. Out of Scope for MVP

- No multi-turn memory
- No advanced personalization
- No multilingual support beyond Portuguese
- No admin dashboard
- No real-time ingestion updates
- No full automation of outdated content detection


## 8. Top 3 Risks

1. Extracted WhatsApp data contains noisy or low-quality answers.
2. Information may be outdated (bureaucratic processes change).
3. LLM usage costs may grow if not tightly controlled.


## 9. Failure Modes (top 5)

| Failure mode | Safe behavior |
|--------------|--------------|
| Ambiguous query | Ask 1 clarifying question |
| No results found | Return "I couldn't find reliable information about this topic." |
| Tool timeout / error | Return partial retrieval answer with disclaimer |
| Unsafe / out-of-scope query | Politely decline and redirect |
| Low confidence answer | Provide best guess + suggest verifying with official source |
