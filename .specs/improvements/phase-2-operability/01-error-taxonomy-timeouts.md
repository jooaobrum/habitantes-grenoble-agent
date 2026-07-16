# P2-01 · Error taxonomy → PT failure messages + timeouts

**Phase:** 2 — Operability · **Priority:** P1 · **Audit:** P1-1

## Problem
`agent.run()` has no try/except ([agent.py:351](../../../api/src/habitantes/domain/agent.py)) — an OpenAI outage becomes HTTP 500 → generic bot apology. The spec's failure table (specific PT messages for Qdrant down / OpenAI down / rate limit) is unimplemented. The `TimeoutError` catch in [search.py:152-169](../../../api/src/habitantes/domain/tools/search.py) is dead (qdrant-client raises its own exceptions), and the Qdrant client has no timeout ([search.py:32](../../../api/src/habitantes/domain/tools/search.py); spec says 3 s).

## Change
- Wrap the two agent layers in `run()`; map exceptions → structured `{error_code, message, retryable}` → the exact PT messages from [spec.md §6](../../features/mvp/spec.md) (Qdrant unreachable, OpenAI unreachable, rate limit).
- Pass `timeout=3` to `QdrantClient`; catch `Exception` where Qdrant errors actually surface (not `TimeoutError`).
- Set the OpenAI request timeout per spec.
- API returns HTTP 200 with the structured error message (bot shows the PT text), not 500.

## Done when
- [ ] Killing the OpenAI key → user receives "Não consegui processar sua pergunta…", HTTP 200, structured error logged.
- [ ] Qdrant unreachable → the spec's Qdrant PT message.
- [ ] No dead `except TimeoutError`; Qdrant client has a 3 s timeout.
