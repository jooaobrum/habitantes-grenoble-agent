# Recommendation retrieval and rendering deviate from PRD #49

Status: accepted (parent #49)

## Context

PRD #49 specified: `search_suggestions` returns the top 3 Clusters for the query,
top 5 members per Cluster plus 3 extras, ranked by 👍 minus 👎 with Mentions older
than 2 years counting half, and the model writes the answer. A first end-to-end
version following that gave poor recall on the pseudo-labelled question set
(`tests/eval/suggestions_pseudo_golden.tsv`) and answers that dropped the counts and
dates. The deviations below were made deliberately, on the tune split only.

## Decision

1. **Pooled member search.** The query fetches up to `candidate_clusters` = 10
   Clusters per search branch (an unfiltered list plus Kind-filtered lists), and
   members are merged across them. A business that sits in two Clusters (grouping is
   by Mention) counts once with pooled votes.
2. **Member dedupe by name** (normalised: case, accents, punctuation), so the same
   business is not listed twice under different Clusters.
3. **Kind inference and Kind keywords in the embedded text.** A Kind is inferred
   from Portuguese category words in the query (`infer_kinds`), and each Cluster's
   embedded text includes its Kind's keywords, so "dentista" reaches Dentists even
   when item-heavy Clusters of other Kinds score higher.
4. **Clustering `similarity_cutoff` = 0.5** (coarser Clusters; fewer, broader
   groups, so one query matches a Cluster holding the relevant members).
5. **Limits:** `max_clusters` 6, `max_members` 20 (replacing top 5 per Cluster plus
   3 extras), and 7 picks rendered in the final answer. The same number (7) is in
   the prompt and in `_MAX_RENDERED_PICKS`.
6. **Picks rendered in code.** The model chooses which returned suggestions are
   relevant by naming them; the agent then rebuilds the list from the tool data
   (name, 👍/👎, last Mention date, Community Business mark, notices). Reason: the
   small chat model dropped counts and dates even with a fixed template (answer-level
   structural-ok 0.00 -> 0.20 with prompt and tool-line changes, 0.88 once rendering
   moved to code). Names the model writes that the tool did not return are dropped;
   matching is word-boundary, accent/case-insensitive, ignores names under 4 characters
   and generic category words, keeps the longer of two nested names, and skips names
   that appear only in a disclaimer sentence ("nenhum", "não encontrei"...). In intent
   `both` the Q&A "Fontes mencionadas" block is left intact.

## Evidence

Retrieval eval (`tests/eval/suggestions_retrieval.py`, seeded tune/holdout split):
tune `recall_shown` 0.28 -> 0.64 over the iterations (changes 1-4 above); holdout
`recall_shown` 0.35, run once. Answer-level results (tune/holdout, v1 vs v2) and their
caveats are in `tests/eval/SUGGESTIONS_ANSWER_REPORT.md`. The holdout is not
independent of retrieval tuning (same seeded split) and the expected names derive
from the same Mentions the collection is built from.

## Known gap

Query-time ranking uses raw 👍 minus 👎 counts. The PRD's "Mentions older than 2
years count half" (`ranking_half_life_years`) is applied only at ingestion, to rank
Clusters and to choose the Cluster summary members. Applying it at query time needs a
weighted score stored per member and a collection rebuild; not done.

## Consequences

More recall and answers that always carry counts and dates, at the cost of larger
tool output, a code-side renderer that must stay in sync with the prompt, and an
old Suggestion with many stale votes outranking a recent one at query time.
