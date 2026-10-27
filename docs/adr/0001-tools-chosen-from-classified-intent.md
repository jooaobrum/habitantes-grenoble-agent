# Tools are chosen from the classified intent

Status: accepted (issue #51, parent #49)

## Context

The agent used to bind every tool on every question and let the model decide
which to call. Adding `search_suggestions` (community picks for a Recommendation
Request) next to the knowledge-base tools would make that choice harder for the
model and would risk clutter and regressions on purely procedural questions.

## Decision

The tool set is derived from the intent assigned by Layer 1 (classification),
not from the model's own choice:

| intent                                  | tools bound                                           |
| --------------------------------------- | ----------------------------------------------------- |
| `qa` (question)                         | knowledge-base tools + web search                     |
| `recommendation`                        | `search_suggestions` + web search                     |
| `both`                                  | knowledge-base tools + `search_suggestions` + web search |
| `greeting`, `feedback`, `out_of_scope`  | none                                                  |

Web search is bound in every tool-using case (when enabled and keyed). The model
still decides *whether and how often* to call a bound tool; it cannot reach a tool
outside its intent's set. A procedural question therefore never sees
`search_suggestions`, and its behaviour is unchanged.

## Consequences

- A misclassified message gets the wrong tool set; the intent prompt carries the
  distinction (who/where to go = recommendation; both only when both parts are real).
- New tools are added by extending the intent -> tools mapping
  (`_KB_INTENTS`, `_SUGGESTION_INTENTS` in `domain/agent.py`), not by prompting.
- Intent `qa` keeps its name for the question intent; `recommendation` and `both`
  are new values of `IntentClassification.intent`.
- Only `qa` answers are cached; recommendation and both are not.
