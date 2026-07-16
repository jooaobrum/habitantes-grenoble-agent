# P2-02 · Feedback buttons end-to-end + JSONL

**Phase:** 2 — Operability · **Priority:** P1 (highest product value) · **Audit:** P1-2

## Problem
"≥85% thumbs-up" is the project's #1 success metric, but the loop doesn't exist: [feedback.py](../../../api/src/habitantes/infrastructure/api/routers/feedback.py) logs to stdout and discards, and [telegram_bot.py](../../../app/telegram_bot.py) never shows 👍/👎.

## Change
- Add an inline keyboard (👍 / 👎) to QA answers in the bot; add a `CallbackQueryHandler`.
- On callback → POST `/feedback` with `chat_id`, `message_id`, `rating`.
- `/feedback` appends `{timestamp, chat_id, message_id, rating, trace_id}` to a JSONL on the mounted log volume (see P0-03).
- ~40 lines total.

## Done when
- [ ] 👍/👎 appear under QA answers in Telegram.
- [ ] Tapping a button writes one line to the feedback JSONL.
- [ ] The feedback file survives `docker compose up --build`.
