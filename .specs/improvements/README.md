# Improvements — Audit Follow-up

Source: [FLABE-AUDIT.md](../../FLABE-AUDIT.md). Each file below is one small, objective spec: problem, change, done-when. Work them **in order** — a phase's tasks assume the prior phase landed.

**Ground rule:** simplicity over machinery. Target load is 30–50 queries/day, 1 engineer, low-cost VPS. Do not add components the audit's "do not build" list rules out (cross-encoder reranker, LangGraph, Redis, webhooks).

## Phase 0 — Stabilize (~½ day) · unblock everything else
| Task | Title | Audit ref |
|---|---|---|
| [P0-01](phase-0-stabilize/01-packaging-test-bootstrap.md) | Packaging + test bootstrap on fresh clone | P1-4 |
| [P0-02](phase-0-stabilize/02-untrack-logs-checkpoints.md) | Untrack committed logs + checkpoints | P1-6, P2-6 |
| [P0-03](phase-0-stabilize/03-single-worker-runtime.md) | Single worker + non-blocking route + log volume | P0-5, P1-6 |
| [P0-04](phase-0-stabilize/04-ingestion-contract-pii.md) | Fix ingestion answer contract + PII whitelist + one embedding model | P0-3, P0-5 |
| [P0-05](phase-0-stabilize/05-prune-ci-dead-code.md) | Prune CI to lint+tests; delete dead code/config/dep | P1-5, P2-4 |

## Phase 1 — Precision (~1–1.5 days) · the core ask
| Task | Title | Audit ref |
|---|---|---|
| [P1-01](phase-1-precision/01-relevance-gate-confidence.md) | Relevance gate + real confidence from cosine | P0-1 |
| [P1-02](phase-1-precision/02-synthesis-prompt-rebalance.md) | Rebalance synthesis prompt (restore fallback) | P0-2 |
| [P1-03](phase-1-precision/03-react-guard-category-tools.md) | ReAct exhaustion guard + one-shot category + trim tools | P0-4, P1-7, P1-8 |
| [P1-04](phase-1-precision/04-eval-negative-latency.md) | Eval: negative cases + fallback_accuracy + latency | P2-1, P2-2 |

## Phase 2 — Operability (~1 day)
| Task | Title | Audit ref |
|---|---|---|
| [P2-01](phase-2-operability/01-error-taxonomy-timeouts.md) | Error taxonomy → PT failure messages + timeouts | P1-1 |
| [P2-02](phase-2-operability/02-feedback-loop.md) | Feedback buttons end-to-end + JSONL | P1-2 |
| [P2-03](phase-2-operability/03-telegram-plaintext.md) | Plain-text Telegram replies | P1-3 |
| [P2-04](phase-2-operability/04-docs-reconciliation.md) | Reconcile docs with code as-built | §6, P2-8 |

**Gate after each task:** `make test` passes. **Gate after Phase 1:** `make eval` green with the new negative-aware cases.
