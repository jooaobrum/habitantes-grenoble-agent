# Suggestions: final-answer evaluation (v1 vs v2)

Scope: the FINAL AGENT ANSWER to recommendation questions, end to end (intent -> tools -> answer).
Dataset: `tests/eval/suggestions_pseudo_golden.tsv` (69 pseudo-labelled rows; expected lists are
partial subsets of what the group said), split with the seeded `split_dataset` of
`suggestions_retrieval.py`: **tune = 25** (the only split used to iterate), **holdout = 44**
(run once for v2 and once for v1, never read while iterating).
Evaluator: `tests/eval/suggestions_answer_eval.py` (deterministic, no LLM judge; unit tests in
`tests/unit/test_suggestions_answer_eval.py`).

## Scoring (exact)

- **coverage** = fraction of expected names present in the answer (`names_match` / normalised
  substring); **hit** = coverage > 0. Coverage is reported separately: expected lists are partial.
- **Structural checks** (all must hold): `has_counts` (every listed item shows 👍 and 👎),
  `has_date`, `has_context` (>= 3 words of context per item), `summary_notice` (summary / top picks /
  not exhaustive), `availability` (confirm availability/hours), `disclosure` (a Community Business
  shown is flagged), `no_quotes` (no quoted text, no "member said"), `negatives_counts` (no
  negative-opinion wording), `no_net_negative` (no item with more 👎 than 👍), `short` (<= 220 words
  and <= 28 lines), `no_weird_ask` (<= 1 "?", no request for personal data).
  Waiver: if the answer is a web fallback (a web call happened and the answer lists no item with
  counts) the four community-format checks (counts, date, context, summary notice) are waived;
  every other check still applies. The waiver applies equally to v1 and v2.
- **Hallucination**: bullet/bold names in the answer whose tokens are absent from the tool outputs
  (suggestions, web, KB chunks) and the question. Heuristic (headings, domains and field labels are
  filtered by a stoplist); it over-flags descriptive web bullets, so read it as an upper bound.
- **PASS = hit AND all structural checks AND hallucinations == 0.**
- Distractors (6 procedural/greeting/feedback messages, written by me, not in any dataset) must not
  take the suggestions path (intent not recommendation/both, no `search_suggestions` call, no 👍).

## v1 vs v2 (answer level)

v1 = commit c0a5d79 (no suggestions path, run from a throwaway worktree, since removed).
v2 = working tree after the iterations below. v2 tune was run twice to show run-to-run noise;
all other cells are a single run.

### Recommendation TUNE (n = 25)

| metric | v1 | v2 run A | v2 run B |
|---|---|---|---|
| hit rate (>= 1 expected name) | 0.92 | 0.72 | 0.56 |
| mean coverage | 0.463 | 0.380 | 0.346 |
| **pass rate** | 0.00 | **0.72** | **0.52** |
| structural-ok rate | 0.00 | 0.96 | 0.88 |
| hallucinated names (answers affected) | 18 (9) | 4 (1) | 6 (2) |
| avg answer length (words) | 219 | 120 | 123 |
| answers showing 👍 counts | 0.00 | 0.96 | 0.88 |
| hit and no hallucination (ignores format) | 0.60 | 0.72 | 0.52 |

### Recommendation HOLDOUT (n = 44, one run each)

| metric | v1 | v2 |
|---|---|---|
| hit rate | 0.750 | 0.773 |
| mean coverage | 0.390 | 0.415 |
| **pass rate** | 0.00 | **0.659** |
| structural-ok rate | 0.00 | 0.841 |
| hallucinated names (answers affected) | 64 (24) | 10 (5) |
| avg answer length (words) | 235.6 | 119.3 |
| answers showing 👍 counts | 0.00 | 0.727 |
| took the suggestions path | 0.00 | 0.864 (6/44 routed to plain `qa`) |
| hit and no hallucination (ignores format) | 0.318 | 0.705 |

Reading this honestly:
- v1 pass rate is 0 by construction: it has no counts/dates/notices, so the PRD format cannot be met.
  The fairer cross-version signals are "hit and no hallucination" (holdout 0.32 -> 0.71), answer
  length (about 236 -> 119 words) and flagged names (64 -> 10).
- On tune, v1's hit rate is higher (0.92 vs 0.56-0.72): v1 dumps long, name-heavy KB/web prose, and
  v2 deliberately shows at most 7 relevant picks. On holdout hit rates are level (0.75 vs 0.77).
- Mean coverage is low for both because expected lists are partial and often long.

### Distractors / anti-overfitting probes (my own questions; final v2 code)

| set | v1 | v2 |
|---|---|---|
| 6 new-topic recommendation probes (manicure, padaria, eletricista, aluguel de bicicleta, crossfit, livraria) took the suggestions path | 0/6 | 6/6 |
| ... structural ok (web-fallback waiver applied) | 0/6 | 6/6 |
| 6 distractors (greeting, titre de séjour, CAF, thanks, TAG, timbre fiscal) kept off the suggestions path | 6/6 | 6/6 |

The 8 "hallucinated" names counted for v2 on the probes are all one web-fallback answer's descriptive
bullets (crossfit: "Localização", "Fica a 10 minutos..."), i.e. evaluator noise, not invented businesses.

### Regression gate (15 `v1reg-*` cases, existing `case_passed` rule, `run_eval.py --suite v1_regression`)

| | v1 | v2 |
|---|---|---|
| pass rate | 15/15 = 100% | 15/15 = 100% |
| flipped cases | - | none |

**Deploy gate: PASS** (regression pass rate did not drop; no flipped cases). Caveat: both runs fail
the report-level `faithfulness` target (0.45 v1, 0.37 v2; target 0.75) and that metric is not part of
`case_passed`; it is pre-existing and was not what the gate compares. `compare_reports.py` was run on
the two regression reports (regression 100% -> 100%, broken 0, fixed 0); its overall verdict is
"failure" only because I ran just the regression suite (no recommendation-suite cases in common), so
the verdict line is not meaningful here. The distractor checks above are the second regression signal.

## Iteration log (tune split only)

Every row is tune (n=25), single run. The evaluator itself was fixed in places during the loop (quote
regex, stoplist, web waiver), so early rows are not strictly comparable to later ones. Run noise on
the same code is large (final code: pass 0.72 vs 0.52), so differences under ~0.15 are not signal.

| loop | change | hit | cov | pass | struct-ok | halluc names | words |
|---|---|---|---|---|---|---|---|
| 0 | baseline (feature as committed) | 0.64 | 0.454 | 0.00 | 0.00 | 14 | 175 |
| 1 | prompt: fixed answer template, override of the generic Q&A format ("Fontes mencionadas"), <= 5 relevant picks, no net-negative | 0.60 | 0.405 | 0.12 | 0.20 | 9 | 119 |
| 2 | tool output lines pre-formatted in the final shape (name, 👍/👎, dd/mm/aaaa, "indicado para"); agent adds a missing summary/availability notice and drops the "Fontes mencionadas" block | 0.72 | 0.451 | 0.20 | 0.28 | 5 | 132 |
| 3 | root cause: the model drops counts/dates even with a template. The agent now renders the list in code from the tool data for the picks the model named (cap 5; invented names dropped; net-negative skipped); model keeps choosing relevance | 0.56 | 0.257 | 0.48 | 0.88 | 10 | 85 |
| 4 | cap 5 -> 7; evaluator fixes (quote rule, field labels, web-fallback waiver) | 0.64 | 0.364 | 0.60 | 0.88 | 13 | 120 |
| 5 | nudge: if the community search ran but the reply names none of its suggestions, force a labelled web search | 0.52 | 0.282 | 0.52 | 0.92 | 4 | 120 |
| 6 | nudge: a recommendation answered without calling `search_suggestions` is sent back to search; availability reminder also on web answers; web fallback limited to 5 short items | 0.72 / 0.56 (2 runs) | 0.38 / 0.346 | 0.72 / 0.52 | 0.96 / 0.88 | 4 / 6 | 120 / 123 |

Root causes found: (a) generic Q&A system prompt (sources block, style) bled into recommendation
answers; (b) a small chat model (gemini-2.5-flash-lite) ignores format rules for counts/dates,
so format is now guaranteed in code; (c) the model sometimes answered without searching, or
found nothing relevant and told the user to search themselves instead of using the web.

## Sample v2 answers (first 4 holdout rows, not cherry-picked)

1. "Quais sites ou plataformas posso usar para procurar emprego em Grenoble?" (intent `qa`, FAIL):
   routed by the intent classifier to the Q&A path (a "sites/plataformas" question, not who/where to
   go to). Answer: prose list (Pôle Emploi, Indeed, LinkedIn, Welcome to the Jungle...) plus a
   "Fontes mencionadas" block; no counts, no availability note. Coverage 0.6.
2. "Quais são as alternativas confiáveis de transporte por aplicativo em Grenoble?" (intent `qa`,
   FAIL): same routing miss; prose mentioning Uber and Bolt (coverage 1.0) with no counts.
3. "Onde posso comprar um cobertor acessível?" (intent `recommendation`, PASS, coverage 0.25):
   Intro "Principais indicações da comunidade (um resumo, não uma lista exaustiva):" then 5 items,
   e.g. `**Action** — 96👍/8👎 · última menção 04/02/2026 — indicado para: ...`, B&M, Carrefour,
   E.Leclerc, Lidl, closing "Confirme a disponibilidade e os horários antes de ir." Note: the one-line
   context is the stored Items ("glitter de carnaval, lojao do 1,99, ..."), which is noisy and not
   about blankets, i.e. a data-quality issue the format cannot hide.
4. "Vocês têm recomendação de lugar para imprimir ...?" (`recommendation`, PASS, coverage 0.5):
   6 items (Fnac 26👍/11👎, Buro+, Tabac, Euro Prim, Imprimerie Armand, Corep) in the same format,
   same notices.

## Known limits and caveats

- Pseudo-labels: expected lists are partial and may miss valid picks; hit/coverage under-count
  correct answers and over-reward long name dumps. Pass rate is a format-and-groundedness gate, not
  a measure of recommendation quality.
- Noise: single runs, temperature 0 does not give determinism here (retrieval + web calls vary).
  Tune final code gave hit 0.72 / 0.56 and pass 0.72 / 0.52 on two runs. Holdout was run once per
  version (hard rule), so its 0.659 has a plausible +-0.1 band.
- The list is rendered in code, so the one-line "context" is the stored Item text, not a model
  rewording; items with poor Items (e.g. "não especificado") look weak. The model still decides
  relevance, which sometimes picks generic supermarkets over a specific expected place.
- Intent routing: 6/44 holdout rows ("sites/plataformas", "alternativas de app") went to `qa`, so
  they get the old format. Not tuned (holdout is off limits for iteration); worth a classifier
  tweak and a new tune-side probe next round.
- Retrieval junk still reaches answers (members like "comida", "Cachaça", "Livro"): outside this
  task (ingestion/clustering).
- Hallucination metric is a token-grounding heuristic: it flags descriptive web bullets and misses
  an invented name that happens to share tokens with the pool.
- v1 per-check rates include answers where the web waiver applied; use pass rate / "answers
  showing 👍 counts" for cross-version format comparisons.
- Regression gate covers 15 procedural cases only; the report-level `faithfulness` target fails for
  both versions (pre-existing).

## Files

- New: `tests/eval/suggestions_answer_eval.py`, `tests/unit/test_suggestions_answer_eval.py`,
  this report.
- Changed: `api/src/habitantes/domain/prompts/synthesis.py` (recommendation instructions),
  `api/src/habitantes/domain/tools/suggestions.py` (answer-ready member lines, dd/mm/aaaa dates),
  `api/src/habitantes/domain/agent.py` (render picks in code, notices, search/web nudges),
  `tests/integration/test_agent_recommendations.py`, `tests/unit/test_suggestions_scope.py`.
- Re-run: `PYTHONPATH=.:api/src uv run python tests/eval/suggestions_answer_eval.py --split tune --details`
  (add `--probes` for the probe/distractor set; `--split holdout` only for a final report).
