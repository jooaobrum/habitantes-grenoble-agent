# P0-03 · Single worker + non-blocking route + log volume

**Phase:** 0 — Stabilize · **Priority:** P0 · **Audit:** P0-5, P1-6

## Problem
[docker-compose.yml:35](../../../docker-compose.yml) runs `--workers 2`. Each worker lazily loads e5-large (~2.2 GB) + BM25 → ~5 GB on a 4 GB VPS (OOM risk). All state is per-process (chat memory, selected-category menu, response cache, rate limits), so a follow-up landing on the other worker loses context ~50% of the time. The chat route is `async def` but calls a synchronous, CPU-bound agent, blocking the event loop. Logs are written inside the container and lost on redeploy.

## Change
- docker-compose: `--workers 1` for the API command.
- Change [chat.py](../../../api/src/habitantes/infrastructure/api/routers/chat.py) `post_chat` from `async def` to `def` so FastAPI runs it in the threadpool. Do the same for the health route if it makes a blocking Qdrant call.
- Mount `./logs:/app/logs` (or the configured `interaction_path` parent) as a volume so logs survive redeploy.

## Done when
- [ ] Only one API worker runs (`docker compose ps` / process check).
- [ ] Menu selection → follow-up question retains category across requests.
- [ ] `docker stats` shows the API stable under ~3 GB at idle.
- [ ] Interaction log persists across `docker compose up --build`.

## Do not
- Do not add Redis/Postgres for shared state — 1 worker makes in-process state correct at this scale.
