# P1-02 · Rebalance synthesis prompt (restore fallback)

**Phase:** 1 — Precision · **Priority:** P0 · **Audit:** P0-2 · **Depends on:** P1-01

## Problem
[synthesis.py:17-29](../../../api/src/habitantes/domain/prompts/synthesis.py) says "SÍNTESE OBRIGATÓRIA … NUNCA comece com 'Não encontrei' se houver contexto". Since context is never empty today (no gate), the fallback is unreachable. Per [IMPROVEMENTS_REPORT.md](../../../tests/eval/IMPROVEMENTS_REPORT.md) this was added to lift answer_relevance (0.52→0.75) against a golden set of only-answerable questions — trading precision on everything else.

## Change
- Once the code-level gate (P1-01) exists, soften the prompt: synthesize from partial context when ≥1 chunk addresses the question; otherwise return the fallback.
- Remove the absolute "NUNCA … Não encontrei" clause — policy now lives in code, not the prompt.
- Keep the guardrails on inventing links/procedures and preferring official sources.

## Done when
- [ ] Prompt no longer forbids the fallback.
- [ ] With relevant context → grounded synthesis unchanged.
- [ ] With gate-rejected context → fallback returned (verified via a negative eval case, see P1-04).
- [ ] `make eval` green.
