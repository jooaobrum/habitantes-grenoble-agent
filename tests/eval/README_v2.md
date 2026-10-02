# Golden Dataset v2 — Schema & Grading Spec

`golden_dataset_v2.json` — 67 cases, human-reviewed. Replaces `golden_dataset.json` (v1, 40
cases) as the canonical eval set once `run_eval.py` is updated to consume it (see
[Runner changes needed](#runner-changes-needed) below — **not yet implemented**, this round
only ships the dataset).

## Why v2 exists

v1 only graded KB retrieval + keyword/similarity on the answer. Modeled on Anthropic's
["Demystifying evals for AI agents"](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents),
v2 adds what was missing:

- **Regression vs. capability split** — `test_type` distinguishes "must always pass" cases
  from "measures how hard this is" cases, so a capability case failing doesn't fail the gate
  the same way a regression case failing does.
- **Web-search coverage** — the agent has a `web_search_grenoble` tool
  (`api/src/habitantes/domain/tools/web_search.py`) that v1 never exercised.
- **Outdated-KB-corrected-by-web cases** — the whole point of the web tool is to catch facts
  that were true when a community thread was written but aren't anymore. v1 had zero cases
  testing this; v2's `kb_web` bucket exists specifically for it.
- **Negative/balance cases** — Anthropic stresses balancing positive and negative tasks. v1
  had none: no out-of-scope refusals, no "KB is empty, don't hallucinate" cases (a rule
  CLAUDE.md already calls out: *"Don't generate an answer when `chunks` is empty"*).
- **Difficulty tagging** — `difficulty` (`basic`/`edge`) lets you read saturation per bucket
  instead of one blended pass rate.

Every case is grounded: `kb`/`kb_web` cases cite a real `thread_id` from
`artifacts/chat-19012021-20022026/synthesis_results.jsonl` (the synthesized corpus that feeds
the production Qdrant collection — ingestion reads `chat-19012021-20022026.txt`, see
`ingestion/config.py`). `web`/`kb_web` facts were verified live via WebSearch on 2026-07-18
(sources in each case's `grounded_in`). All 67 cases were reviewed by the project owner via
`golden_v2_review.md` before being added — several were corrected or expanded during that pass
(e.g. `visa-basic-02`'s timbre fiscal amount, `work-edge-01`'s passport-talent diploma rule).

## Schema

```json
{
  "id": "visa-basic-01",
  "category": "Visa & Residency",
  "question": "…",
  "difficulty": "basic" | "edge",
  "test_type": "regression" | "capability",
  "expected_source": "kb" | "kb_web" | "web" | "none",
  "expected_thread_ids": [1948],
  "expected_answer_keywords": ["OFII", "e-mail", "bai-grenoble@ofii.fr"],
  "ground_truth_answer": "…verified answer text, used as the semantic-similarity reference…",
  "grounded_in": "synthesis_results#thread-1948 (confirmed, conf=1.0)",
  "notes": "…why this case exists, caveats, review history…"
}
```

| Field | Notes |
|---|---|
| `suite` | Optional tag: `recommendation` or `v1_regression` (the Suggestions comparison, `compare_reports.py`). Absent on the original cases. |
| `category` | One of the 19 canonical `en_name`s in `config/base.yaml` `categories:`. `null` for negative cases (they're intentionally uncategorizable / out of scope). |
| `difficulty` | `basic` = everyday question a resident would actually ask. `edge` = niche, multi-part, or tests a specific point of confusion. |
| `test_type` | `regression` = should ~always pass; a drop is a real bug. `capability` = expected to be hard; a drop is a measurement, not necessarily a blocker. |
| `expected_thread_ids` | Empty for `web` and `none` cases (nothing to retrieve, or retrieval isn't the point). |
| `ground_truth_answer` | The verified correct answer. Doubles as the reference text for a semantic-similarity metric. |
| `grounded_in` | Provenance/evidence — always re-derivable. Cite the exact thread(s) and/or web sources with the verification date. |

## The four buckets (`expected_source`)

### `kb` (49 cases)
Answerable from the KB alone. Graded like v1: retrieval (`expected_thread_ids` hit/recall) +
answer content (keyword coverage / semantic similarity against `ground_truth_answer`). Covers
all 19 canonical categories with at least 2 basic cases each.

### `kb_web` (5 cases) — **highest-value bucket, added in v2**
The KB has a real, retrievable anchor, but it's stale, incomplete, or was simply wrong and
needs a current/correct fact from the web to answer well:

- `visa-kbweb-01` — KB mentions the titre de séjour timbre fiscal but no amount; the amount
  materially changed (May 2026 fee hike, first-issue 225€→350€).
- `bank-kbweb-01` — KB states a specific stale Boursorama welcome-bonus amount and promo code.
- `travel-kbweb-01` — KB thread claims Ouigo direct-to-Grenoble service is winter-only; current
  reality is broader.
- `univ-kbweb-01` — KB discusses CVEC payment method but omits the amount (105€ for 2025-2026).
- `work-edge-01` — the community answer says "attestation de réussite" isn't accepted for the
  passport talent visa; the official préfecture document checklist says it is. This is the
  sharpest case in the set: the retrieved KB chunk **actively contradicts** the correct
  current rule, so a good agent must not just parrot it.

Grading intent: check the answer contains the *current* fact (`expected_answer_keywords`),
not the stale KB fact. A regression here (agent repeats the stale number/claim) is a real bug,
not just low recall.

### `web` (3 cases)
No KB anchor — pure factual/current Grenoble info (population, SMIC, tram line count).
Grading intent: check `web_used=True` (agent's state, see `agent.py`) and that the answer
contains the current value. These need periodic re-verification (SMIC and population drift).

### `none` (10 cases) — negative cases, added in v2
Two families:
- **out-of-scope** (`neg-oos-*`, 5 cases) — not about Grenoble (other city/country, world
  trivia, generic creative requests). Should trigger the `out_of_scope` intent branch
  (`prompts/intent.py`) and get refused/redirected, not answered.
- **empty-KB / unknowable** (`neg-empty-*`, 5 cases) — a real Grenoble topic, but asking for
  something no tool can know: a fabricated doctor, a live queue length, a personal dossier
  number, live community-group membership, personal case-status ETA. Grading intent: the
  agent must **not fabricate a specific answer**. This directly operationalizes the CLAUDE.md
  rule *"Don't generate an answer when `chunks` is empty"* and extends it to web/live data too.

### `suggestions` (21 cases, `suite: recommendation`) — added for the Suggestions feature
Recommendation Requests ("who/where do you recommend for X?"), all `capability`. They
have no `expected_thread_ids` (the Suggestions collection is not Q&A threads) and carry
an `expected_suggestions` object: `kind`, `topic`, `item_terms`, `names` and
`verification`. Pass rule: `keyword_coverage >= 0.5` on `expected_answer_keywords`
(Kind/Item terms, plus a name where the chat export shows one) AND the answer shows 👍
counts (`cites_community_counts`). `names` is empty or only chat-confirmed, and every
case is marked `needs_corpus_verification` until the maintainer checks it against the
built Clusters. See EVAL_GUIDE.md, "Suggestions evaluation".

### `v1_regression` suite (15 cases)
Regular `kb`/`regression` cases (`v1reg-*`) lifted from the v1 set with their v1 thread
ids and keywords, used to check that Suggestions do not degrade Q&A.

## Known caveats (flagged in individual `notes`)

- `travel-kbweb-01` and `bank-kbweb-01` cite a KB thread with `answer_confirmed=False`
  (community-sourced, not human-reviewed in the original synthesis pipeline) — kept because
  the reviewer verified the content directly, but a future re-sync of the source corpus should
  re-check these two first.
- A few `ground_truth_answer` values contain point-in-time facts (holiday dates, event dates,
  promo prices) that will drift — flagged case-by-case in `notes`. `nightlife-basic-02` was
  deliberately reclassified `basic/regression` → `edge/capability` for this reason: repeating a
  stale date isn't a "basic" behavior to require forever.
- `visa-basic-02`'s renewal timbre-fiscal amount (250€) was added during human review with a
  quoted source rather than an independent WebSearch — reasonable given the reviewer supplied
  it directly, but worth an independent re-check next time this file is revisited.

## Runner changes needed

Not implemented this round. For `golden_dataset_v2.json` to actually run through
`tests/eval/run_eval.py`, it needs:

1. **Branch on `expected_source`** instead of always calling `hybrid_search` + keyword/semantic
   scoring:
   - `kb` → today's Layer 1 (retrieval) + Layer 2 (generation) path, unchanged.
   - `kb_web` → same as `kb`, but the keyword check should target `expected_answer_keywords`
     (the *current* fact), and a new metric should check whether the agent's final answer
     contains the stale KB fact as a failure signal (regex/substring check against the known
     stale value, stored in `notes` today — would need promoting to a structured field like
     `stale_fact_markers` if this gets automated).
   - `web` → skip `hybrid_search` entirely; assert `state["web_used"] is True` (or check
     `state["sources"]`) and run the keyword/semantic check against the final answer.
   - `none` → new metric: **non-fabrication check**. No existing metric in
     `api/src/habitantes/eval/metrics.py` does this — would need an LLM-judge prompt asking
     "does this answer state or imply a specific fact/number/name not present in the provided
     context, i.e. did the model fabricate?" Pass = agent declined/gave general guidance
     without inventing specifics.
2. **Split gate reporting** by `test_type`: aggregate `regression` cases against a strict
   target (close to today's thresholds in `TARGETS`), report `capability` cases as a measured
   score without gating the build on them (per Anthropic's guidance — capability evals start
   low and are meant to be improved over time, not blocked on).
3. **Category coverage report** — since v2 spans all 19 categories, it's worth reporting
   pass-rate per category, not just a single blended number, to catch a category silently
   regressing.
