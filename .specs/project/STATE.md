# STATE

- **Decisions:**
  - Ingestion pipeline is complete and offline-only
  - Using gpt-4o-mini for all LLM calls (classification + synthesis)
  - Long polling for Telegram (simpler than webhooks)
  - In-memory short-term memory (no persistence needed for MVP)
- **Blockers:**
  - Need Telegram bot token from BotFather
  - Need to verify Qdrant collection is populated
- **Next steps:**
  - T1.1: Bootstrap project structure
