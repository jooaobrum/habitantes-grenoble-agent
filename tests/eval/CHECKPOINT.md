# Prompt-engineering eval loop — checkpoint

Resumable log for the prompt-refinement loop against `golden_dataset_v2.json` (67 cases).
If this session gets interrupted, read this file top to bottom before doing anything else —
it says exactly what's been tried, what worked, and what's next.

## Scope guardrail (do not violate)

Only touch:
- `api/src/habitantes/domain/prompts/synthesis.py` (system prompt)
- `api/src/habitantes/domain/tools/web_search.py` (tool **docstring** only — it's the
  LLM-facing tool description read by `bind_tools()`, not decision logic; no code/control-flow
  changes here)
- Deterministic eval code in `api/src/habitantes/eval/metrics.py` / `tests/eval/run_eval.py`
  only if a case is diagnosed as genuinely mis-specified (see rule below)

Do NOT touch `agent.py` control flow, `state.py`, contracts, or ingestion.

**Golden dataset changes are last resort.** Never edit `golden_dataset_v2.json` on the first
or second failed attempt at a case. Only after ≥2 genuine prompt iterations still fail a case,
diagnose whether the case/keyword spec itself is miscalibrated, and if so, propose the change
explicitly before applying it.

## Baselines (backed up in `tests/eval/checkpoints/`)

- `synthesis.v0.baseline.py`, `web_search.v0.baseline.py` — prompt/tool state before any edits.
- `report_v2.v0.baseline.json` — full eval report before any edits (iteration 0 / baseline).

## Iteration 0 — baseline (already run before this session started editing)

Command: `python tests/eval/run_eval.py --dataset tests/eval/golden_dataset_v2.json`

| Bucket | n | pass_rate |
|---|---|---|
| overall | 67 | 94.03% |
| regression | 48 | 97.92% |
| capability | 19 | 84.21% |
| kb | 49 | 100% |
| kb_web | 5 | **40%** ← weakest |
| web | 3 | **66.7%** |
| none | 10 | 100% |

Regression gate: **all_regression_targets_met = True** (already passing before this session).

### Failing cases identified (diagnosis target)

1. **bank-kbweb-01** (kb_web, capability) — FAIL. `web_used=False`, `contains_stale_fact=True`.
   Agent answered from the stale KB chunk (150€ bonus, code JAOL1582) without calling
   `web_search_grenoble` to check the current 160€/BRSOPE160 offer.
2. **travel-kbweb-01** (kb_web, capability) — FAIL. `web_used=False`, `contains_stale_fact=True`.
   Repeated the KB's "Ouigo direct only in winter" claim verbatim; didn't verify it's now
   year-round.
3. **work-edge-01** (kb_web, capability) — FAIL. `web_used=False`, `contains_stale_fact=True`.
   Repeated the KB's wrong claim that attestation de réussite isn't accepted for passport
   talent, contradicting the official préfecture checklist.
4. **univ-kbweb-01**, **visa-kbweb-01** — already PASS (kw_cov low but semantic_similarity
   carries them over threshold). Leave alone.
5. **web-basic-01** (web, regression) — FAIL. `web_used=True` (tool WAS called, this is a
   different failure mode), but `keyword_coverage=0.4`. Cited bien-dans-ma-ville/Le Dauphiné
   with conflicting numbers (156.140 vs 154.798) and never named INSEE or a "155"-prefixed
   figure the way `expected_answer_keywords` wants.

### Root cause (code-level, confirmed by reading `agent.py:437-561`)

The only code-level nudge toward `web_search_grenoble` fires when a KB search returns **zero**
relevant chunks (`agent.py` around line 547). In all three kb_web failures the KB search
returns a relevant-looking chunk (it clears the relevance floor), so the nudge never fires —
the decision to double-check via web is **entirely prompt-driven**. The current prompt's
web-search trigger criteria (`synthesis.py` "ESCOLHA DE FERRAMENTAS") are abstract ("KB
insufficient", "factual/current question", "confirm a fact that may be outdated") and don't
give the model concrete signal for *when a KB chunk that looks complete is still likely stale*.
All three kb_web failures fall into the same pattern: **money amounts/promos, transport
schedules, and visa/document requirement lists** — categories that change over time by nature.

For web-basic-01, the issue is different: web tool was invoked correctly, the failure is in
*source selection/synthesis discipline* — the prompt's guardrail about preferring official
sources (rule 2) only mentions immigration/CAF bodies, not INSEE, and doesn't extend
explicitly to resolving conflicts between multiple web results.

## Plan

1. **Iteration 1**: add an explicit "time-sensitive triggers" list (money/promo, transport
   schedule, visa/document rules) to both the system prompt's tool-selection section and the
   `web_search_grenoble` tool docstring, instructing the agent to verify via web even when the
   KB chunk looks complete. Also extend guardrail 2 to name INSEE and cover web-result
   conflicts explicitly (target web-basic-01).
2. Test in isolation (not full 67-case suite) on the 4 target-fixed cases + 2-3 guard cases
   (previously-passing kb/kb_web/web cases) using `tests/eval/checkpoints/run_isolated.py`.
3. Iterate prompt wording based on isolated results before spending a full 67-case run.
4. Once isolated cases look right, run the full suite once for final regression validation.
5. Run `pytest tests/ -v`.
6. Write the final report.

## Iteration 1 — done, isolated-tested

Changes made (see diff in `api/src/habitantes/domain/prompts/synthesis.py` and
`api/src/habitantes/domain/tools/web_search.py`):

1. Added "SINAIS DE DADO PERECÍVEL" section: money/promo amounts, transport
   schedules/routes, visa/document rule lists are inherently time-sensitive → always
   verify via `web_search_grenoble` even when the KB chunk looks complete.
2. Extended GUARDRAILS rule 2 to name INSEE (demographic data) and cover conflicts
   between web results, not just KB vs. official-body conflicts.
3. Added a French-query tip: include "INSEE" in the query for demographic questions,
   and cite INSEE explicitly if it shows up in results (targets `web-basic-01`).
4. Mirrored the same perishable-data triggers in the `web_search_grenoble` tool
   docstring (LLM-facing tool description read by `bind_tools()` — prompt content,
   not control-flow).
5. **GUARDRAIL 5 (added after a regression was caught mid-loop)**: explicitly forbids
   asserting a specific numeric OR categorical detail from the KB alone, for
   perishable-data topics, unless `web_search_grenoble` was already called in this
   response. The first version only blocked "numbers"; a qualitative claim
   ("only in winter") slipped through and caused `visa-kbweb-01` to regress
   (previously passing via semantic_similarity, then started confidently repeating a
   stale 225€ figure). Broadened wording fixed it — verified 3/3 stable reruns.
6. Added a short worked example + a "check before you answer" self-check line,
   plus an explicit "many corroborating community threads ≠ current" clause — targeted
   at `travel-kbweb-01`, which still fails after 4 escalating attempts (see below).

### Isolated test results after iteration 1 (temperature=0, so results below are stable
### across reruns — verified 3x on the previously-flaky cases)

| case | bucket | before | after |
|---|---|---|---|
| bank-kbweb-01 | kb_web/capability | FAIL | **PASS** |
| travel-kbweb-01 | kb_web/capability | FAIL | **still FAIL** (see below) |
| work-edge-01 | kb_web/capability | FAIL | **PASS** |
| univ-kbweb-01 | kb_web/capability | PASS | PASS (no regression) |
| visa-kbweb-01 | kb_web/capability | PASS | PASS (regressed mid-loop, fixed by GUARDRAIL 5) |
| web-basic-01 | web/regression | FAIL | **PASS** |
| web-basic-02 | web/regression | PASS | PASS |
| web-basic-03 | web/regression | PASS | PASS |

Guard sweep (no regressions found): 19 `kb`-bucket cases (one per category) all PASS;
all 10 `none`-bucket cases (5 out-of-scope + 5 empty-KB) PASS.

### Known residual gap: `travel-kbweb-01`

Root cause (confirmed via direct agent trace, see debug output): `hybrid_search`
returns **5 corroborating** Travel & Transport threads for this query, all repeating
the same "Ouigo direct only in winter" claim. At temperature=0 the model treats
multi-source community agreement as sufficient confidence and never calls
`web_search_grenoble`, despite: the explicit "SEMPRE" instruction, GUARDRAIL 5's
categorical-claim ban, a worked example, and an explicit "corroboration ≠ current"
clause. Four genuine prompt-only attempts made, escalating each time; none worked for
this specific case.

**This is not a mis-specified test** — `README_v2.md` already flags this exact case as
"HIGH VALUE... a strong illustration of why info_might_be_outdated / web fallback
matters," i.e. it's meant to be hard (`test_type: capability`). Leaving it failing and
documenting it, per the instruction to only reconsider a case after genuinely trying —
this went well past 2 attempts. A real fix would likely need a code-level nudge (e.g.
extending the existing empty-KB web nudge in `agent.py` to also fire on
high-corroboration-but-uncertain topics), which is out of scope for this prompt-only
pass and would need its own design discussion given it touches orchestration logic.

## Full run 1 (iteration 1, as first written) — RESULTS

`report_v2.json` after iteration 1, full 67 cases:

| Bucket | n | before (v0) | after (iter 1) |
|---|---|---|---|
| overall | 67 | 94.03% | **97.01%** |
| regression | 48 | 97.92% | **100%** |
| capability | 19 | 84.21% | **89.47%** |
| kb | 49 | 100% | 100% (unchanged) |
| kb_web | 5 | 40% | **60%** (3/5 — travel-kbweb-01 still fails) |
| web | 3 | 66.7% | **100%** |
| none | 10 | 100% | 100% (unchanged) |

`all_regression_targets_met = True` (was already True at baseline — now with a
stronger margin and 100% regression pass rate instead of 97.92%).

## Overfitting check (user-requested, important — read this before trusting the numbers above)

The user correctly flagged the risk: iterating a prompt directly against the exact
failing golden-dataset cases can produce a prompt that memorizes those specific
facts/phrasings instead of generalizing the underlying behavior. Response: built
`scratchpad/probe_generalization.py` — 6 **held-out** questions never in
`golden_dataset_v2.json`, covering the same 4 trigger categories with different
topics/phrasing, plus 2 distractors to check for harmful over-triggering:

1. money-promo: Revolut referral bonus (dataset only tested Boursorama)
2. transport-schedule: Lyon-airport FlixBus frequency (dataset only tested Ouigo Paris)
3. visa-document: OFII chest X-ray requirement (dataset only tested passport-talent diploma)
4. factual-web: current mayor (dataset only tested population/SMIC/tram — this one was
   already covered by the PRE-EXISTING criterion (b), not by iteration 1, so it's a
   control to confirm iteration 1 didn't break pre-existing behavior)
5. distractor: haircut price (a money topic with NO official/authoritative web source —
   checks GUARDRAIL 5 doesn't cripple ordinary community-tip price answers)
6. distractor: out-of-scope question in casual phrasing

Ran these 3 times: against `v0` baseline, against iteration-1-as-first-written (with a
**train-specific** worked example, since the fix was drafted while fighting
`travel-kbweb-01`), and against iteration-1 after **genericizing** that example.

**Finding**: the train-specific example only helped train-shaped questions and didn't
generalize — probes 2 and 3 above still hedged instead of calling the web tool.
Genericizing the example (describing the pattern abstractly: "a value/deadline/rule
stated with confidence, no verification date" instead of literally "trem X vai direto
pra Y") *improved* generalization: probes 2 and 3 now correctly call
`web_search_grenoble` and return real, current, sourced answers. This is the opposite
of what over-fitting would predict (a more specific, test-shaped example should help
the near-identical test case at least) — and indeed the specific case that motivated
the train example (`travel-kbweb-01`) still fails either way. Net effect: the
generic-example version is both a better generalizer AND not worse on the literal test
case, so it's the version that shipped (see `synthesis.py` as committed).

Distractors (5, 6) never showed harmful over-triggering in any version tested — price
questions with no official source still get answered directly with community numbers,
out-of-scope questions still get refused cleanly.

Residual honest finding: probe 1 (money-promo/Revolut) never triggered an actual web
call in any version — the model treats "hedge and tell the user to check for an
updated code" as sufficient when the KB has no single stale number to actively
contradict. This is safe (no false fact asserted) but weaker than the ideal behavior.
Documented as a known limit rather than further prompt-patched, per the instruction not
to over-fit — see final report for the recommendation to address this with a stronger
code-level nudge (extending the existing empty-KB web nudge in `agent.py`) rather than
more prompt escalation.

## Full run 2 (genericized example) — RESULTS, and a real regression caught

`report_v2.json` after genericizing the example (full 67 cases):

| Bucket | before (v0) | after (iter 1, train example) | after (iter 1, generic example) |
|---|---|---|---|
| kb_web | 40% (2/5) | 60% (3/5) | **80% (4/5)** — travel-kbweb-01 still fails, consistently |
| none | 100% (10/10) | 100% (10/10) | **90% (9/10)** — NEW REGRESSION |

Genericizing the example didn't just generalize better on held-out probes — it also
pushed one more literal dataset case (comparing 60%→80% on kb_web) without the
train-specific tuning. Good sign this isn't overfitting.

BUT: `neg-empty-05` ("quantos dias exatos falta pra minha CAF processar meu pedido")
flipped from PASS (non_fabrication=1.0 at both v0 and the first iter-1 run) to FAIL
(non_fabrication=0.0). Root cause: SINAIS DE DADO PERECÍVEL item 3 lists "CAF" as a
topic to verify via web — correct for general CAF procedure/document questions, but
this question asks for the user's PERSONAL, LIVE case status, which no source (KB or
web) can know. The agent, now primed to proactively web-search CAF topics, pulled real
general processing-time statistics (18 days avg, up to 36.5 days) and presented them
with enough numeric confidence that the non-fabrication judge read it as answering the
personal ETA question with fabricated precision — even though the underlying stat was
real and sourced.

**Fix applied**: added an explicit carve-out right after the SINAIS DE DADO PERECÍVEL
list — perishable-data verification does not apply to the user's personal/live case
status (exact ETA, live queue position, personal dossier state); no source can know
that, general web-verified statistics must stay explicitly labeled as general
estimates, not framed as the answer to "my case." Re-tested: `neg-empty-05` back to
PASS, all 6 `none`-bucket cases spot-checked pass, and all 7 previously-fixed
kb/kb_web/web target cases still pass (no new regression from the carve-out).

## Full run 3 (carve-out for personal/live status) — RESULTS

`report_v2.json`, final version: **67/67 pass_rate by the automated metric (100%)**.
`all_regression_targets_met = True`. `neg-empty-05` fixed, no other regressions.

**BUT — read this before trusting "100%" at face value**: `travel-kbweb-01`'s pass in
this run is a **metric artifact, not a real fix**. Re-verified by direct inspection
(2x isolated rerun, byte-identical at temp=0): the agent still never calls
`web_search_grenoble` for this case and still asserts the same stale "Ouigo direct
only in winter" claim — it just rephrased into two bullet points ("Durante o inverno:
... Fora do inverno: ...") that dodge the literal `stale_fact_markers` substring check
(`"apenas durante o inverno"`, `"só no inverno"`, `"só durante o inverno"`). The
underlying capability gap documented earlier (multi-source KB corroboration biasing
the model against calling web, even at temp=0, even after 4 escalating prompt
attempts) is UNCHANGED. This is being reported honestly in the final report rather
than claimed as a win — true genuinely-verified status is 66/67 automated-pass +
1 known, unresolved, metric-masked capability gap.

Recommendation (not implemented, out of scope for a prompt-only pass): replace
`contains_stale_fact`'s substring match with a semantic/LLM-judge check (same pattern
as `non_fabrication`) so paraphrases of a stale claim don't slip through. Flagging
for the Eval Engineer reviewer.

## pytest: 2 pre-existing failures, both confirmed unrelated to this work (reproduced
## identically with all changes `git stash`ed) — `test_chat_success` and
## `test_retrieval_smoke` both fail on a dummy/missing OpenAI API key in the pytest
## environment, not on anything touched here.

## STATUS: DONE. All changes are in `api/src/habitantes/domain/prompts/synthesis.py`
## and `api/src/habitantes/domain/tools/web_search.py` (docstring only). Baselines and
## every intermediate report are preserved in `tests/eval/checkpoints/` for rollback.
## See the final report delivered to the user for the full narrative.
