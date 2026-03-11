# Project Overview - Grenoble Brazilian Expats Chatbot

## 🎯 What is this?

An AI-powered chatbot that helps Brazilian expats in Grenoble, France navigate bureaucracy, housing, healthcare, and daily life questions. The bot centralizes knowledge from years of WhatsApp group conversations into an accessible, 24/7 assistant available on Telegram.

**Status**: MVP in development
**Launch Target**: Q1 2025
**Expected Users**: ~300 Brazilian expats in Grenoble

---

## 🤔 The Problem

Brazilian expats in Grenoble repeatedly ask the same questions in WhatsApp groups:
- *"Como renovar meu titre de séjour?"*
- *"Onde conseguir apartamento?"*
- *"Como marcar consulta médica?"*
- *"Qual banco abrir conta?"*

**Current pain points**:
- ❌ Information is fragmented across hundreds of chat threads
- ❌ Answers are buried in long conversations (Jan 2021 → Feb 2025)
- ❌ No easy way to search past discussions
- ❌ Information becomes outdated (bureaucracy changes)
- ❌ New arrivals ask the same questions repeatedly
- ❌ Group members get fatigued answering the same things

**Impact**:
- Hours wasted searching or waiting for answers
- Missed deadlines (visa renewals, CAF applications)
- Frustration from outdated information
- Community fatigue

---

## ✨ The Solution

A **knowledge-based chatbot** that:

### What it does
1. **Answers questions instantly** - No waiting for someone online
2. **Searches historical knowledge** - 5 years of WhatsApp conversations indexed
3. **Provides reliable sources** - Links to official websites (préfecture, ANEF, CAF)
4. **Understands Portuguese** - Native language support
5. **Available 24/7** - Always ready to help
6. **Categorizes topics** - Visa, housing, healthcare, banking, transport, education, CAF

### How it works (simplified)
```
User asks question (Telegram)
    ↓
Layer 1: classify intent (greeting / qa / feedback / out_of_scope)
    ↓
Layer 2: ReAct Agent (LLM + tool calling loop)
    │
    ├── Check response cache (if QA) → Returns instantly if found
    ├── If miss: Tool calling loop (max 5 iterations)
    └── Otherwise → responds directly (no tool needed)
    ↓
Returns response in Portuguese
```

### Example interaction

**User**: Como renovar meu titre de séjour passeport talent em Grenoble?

**Bot**:
> Para renovar seu **titre de séjour passeport talent** em Grenoble, você precisa:
>
> **Documentos necessários:**
> - Formulário CERFA preenchido
> - Passaporte válido
> - Comprovante de trabalho (contrat de travail)
> - Comprovante de residência
> - Fotos 35x45mm
>
> **Onde renovar:**
> Agendamento pelo site da ANEF (antiga préfecture):
> https://administration-etrangers-en-france.interieur.gouv.fr/
>
> **Prazo:**
> - Solicite 2-3 meses antes do vencimento
> - Tempo de processamento: 2-4 meses
>
> **Dica importante:** Vagas para agendamento são limitadas. Tente acessar o site logo cedo (antes das 9h) ou aos domingos à noite.
>
> 📎 *Baseado em experiências recentes da comunidade (Jan-Fev 2025)*

---

## 👥 Who is this for?

### Primary Users
- **Brazilian expats in Grenoble** (current: ~300 people)
- **New arrivals** navigating French bureaucracy
- **Long-term residents** with occasional questions

---

## 🛠️ Tech Stack (high-level)

### Core Components
- **Interface**: Telegram Bot (WhatsApp planned later)
- **AI Models**:
  - OpenAI GPT-4o-mini (answer synthesis)
  - `intfloat/multilingual-e5-large` (Dense embeddings)
  - `Qdrant/bm25` via `fastembed` (Sparse embeddings)
- **Knowledge Base**: Qdrant vector database (Hybrid Search + RRF)
- **Agent Architecture**: Two-Layer ReAct (LangChain tool calling)
- **Backend**: FastAPI (Python)
- **Deployment**: Low-cost VPS

### Data Sources
- WhatsApp group export (Jan 2021 - Feb 2025)
- ~5,000+ Q&A pairs extracted and curated
- Categorized by topic (visa, housing, healthcare, etc.)


## 📚 Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technical architecture, components, and implementation details
- **[IDEATION_BRIEF.md](IDEATION_BRIEF.md)** - Original problem definition and project scope
- **README.md** *(coming soon)* - Setup instructions and developer guide
- **DEPLOYMENT.md** *(coming soon)* - Production deployment guide


## 🎯 MVP Scope

### ✅ In Scope
- Telegram bot interface
- Question answering (single-turn)
- Portuguese language support
- 20 topic categories
- Source attribution
- Basic feedback (thumbs up/down)
- Knowledge base from WhatsApp history

### ❌ Out of Scope (for now)
- Multi-turn conversations with memory persistence
- WhatsApp interface
- User personalization
- Real-time knowledge updates
- Admin dashboard
- Multi-language support
- Voice messages
- Image understanding

---

## 💰 Cost Structure

**Target**: <$30/month total

| Component | Monthly Cost | Notes |
|-----------|--------------|-------|
| VPS (Hetzner CPX11) | $5-8 | 2 vCPU, 4GB RAM |
| OpenAI API | $2-5 | ~1M tokens/month estimate |
| Domain (optional) | $1 | For webhook URL |
| **Total** | **~$8-14** | Scales with usage |

**Cost optimization strategies**:
- Use gpt-4o-mini (20x cheaper than GPT-4)
- Implement response caching for repeated questions
- Rate limit Telegram bot to prevent spam expenditure
- Limit response length (max_tokens: 1024)
- Use local embeddings (no OpenAI embeddings API)

---


## 📈 Roadmap

### Phase 1: MVP (Current)
- Core Q&A functionality
- Telegram interface
- 5 super users
- 20 categories

### Phase 2: Refinement (Q3 2025)
- Multi-turn memory
- WhatsApp integration
- Improved search quality
- Knowledge base updates

### Phase 3: Scale (Q4 2025)
- Other Brazilian expat communities (Paris, Lyon, Toulouse)
- Portuguese expats
- Admin dashboard
- Automated content updates

### Future Ideas
- Voice message support
- Image understanding (documents, screenshots)
- Proactive notifications (visa expiration reminders)
- Integration with official APIs (CAF, préfecture)
- Mobile app (React Native)

---

**Last Updated**: March 2025
**Version**: 0.1.0 (Pre-MVP)
