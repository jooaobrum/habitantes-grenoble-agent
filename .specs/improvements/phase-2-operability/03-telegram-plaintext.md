# P2-03 · Plain-text Telegram replies

**Phase:** 2 — Operability · **Priority:** P1 · **Audit:** P1-3

## Problem
Replies use legacy `parse_mode=MARKDOWN` ([telegram_bot.py:146-148](../../../app/telegram_bot.py)). GPT-style `**bold**`, `###`, or an unbalanced `*`/`_`/`[` raises `BadRequest` → the user sees "erro técnico" instead of the answer.

## Change
- Simplest: send answers as plain text (no `parse_mode`).
- Or: try Markdown, and on `BadRequest` resend the same text plain.
- Keep the sources footer working under whichever mode is chosen.

## Done when
- [ ] An answer containing `**`, `###`, or a lone `*` is delivered intact, not as an error.
- [ ] Sources footer still renders.
