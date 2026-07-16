# P1-03 · ReAct exhaustion guard + one-shot category + trim tools

**Phase:** 1 — Precision · **Priority:** P0/P1 · **Audit:** P0-4, P1-7, P1-8

## Problem
Three related correctness gaps in the agent/tools:
- **Exhaustion (P0-4):** if the model still requests a tool call on the final allowed iteration, the loop exits with a `ToolMessage` as the last message and `answer = msgs[-1].content` ([agent.py:261-311](../../../api/src/habitantes/domain/agent.py)) — a raw chunk dump goes to the user.
- **Sticky category (P1-7):** a menu selection persists until the next greeting ([agent.py:65-84](../../../api/src/habitantes/domain/agent.py)) and is force-injected into every tool call ([agent.py:274-279](../../../api/src/habitantes/domain/agent.py)). Pick "1 · Visto", ask a visa question, then ask about dentists → still filtered to Visa.
- **Deep-dive tools (P1-8):** `list_subcategories` scrolls only 1,000 of 2,853 points; `get_category_chunks` returns arbitrary-order results that bypass all relevance logic ([search.py:197-262](../../../api/src/habitantes/domain/tools/search.py)).

## Change
- After the loop, if the last message is not an assistant message with content → make one final LLM call with tools disabled (or return the fallback). ~5 lines.
- Clear the stored category after it is used for one QA answer (menu selection applies to the **next** question only).
- Simplest: drop `get_chunks_by_category` and keep only `search_knowledge_base` + `list_knowledge_subcategories`. If keeping subcategories, paginate fully once at startup.

## Done when
- [ ] Forcing tool calls to the last iteration never leaks raw chunk text to the user.
- [ ] Category filter applies to exactly one question after selection, then clears.
- [ ] No tool returns results that skip the relevance gate.
- [ ] `make test` passes (update agent/tool tests accordingly).
