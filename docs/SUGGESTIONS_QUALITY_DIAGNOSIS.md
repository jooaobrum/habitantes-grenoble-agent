# Suggestions: where quality is lost, and a proposal

Measured on the real 2021-2026 export (6,118 Mentions, 1,970 Suggestions, 761 Clusters).
Question-level numbers use the 25-question **tune** split only. Data-quality numbers are on
random samples and involve no questions. "LLM proxy" = `google/gemini-2.5-flash` judging, not hand
labels, so treat percentages as +-5 points.

## Funnel for the 88 expected names of the tune questions

| Stage | Names | Share |
|---|---|---|
| Expected | 88 | 100% |
| Stored in the collection (ingestion) | 84 | 95% |
| Shown to the agent | 56 | 64% |
| Lost: member's Clusters not retrieved | 17 | 19% |
| Lost: in a returned Cluster but cut by the member cap / ranking | 11 | 12% |
| Lost: not stored | 4 | 5% |

Of the 493 members shown across those questions, only **43%** are relevant to the question (LLM
proxy). Showing more members raises recall but lowers precision.

## Where it degrades, in pipeline order

1. **Extraction / scope (biggest source of noise).** On 200 random Suggestions: 59% real named
   businesses, 22% generic words (Coxinhas, Supermercado, litiere, batata palha), 7% private people
   (Gregory, Julie Tyrant), 6% apps/platforms (Le Bon Coin, Netflix, Remessa Online), 4% public
   bodies or associations (UGA, Consulado). The Kind is wrong for 24%. Products is worst (22 of 32
   not a business), then Other (13/27), Professional Services (11/24), Places & Outings (9/31).
   Counting mentions does not filter it: real-business rate is 59% for single-mention and 60% for
   multi-mention Suggestions. Only 16% of Mentions have no Items; context is rarely empty.
2. **Kind assignment.** Kind is assigned per Mention, so one business splits across Kinds: 8% of
   names, but 35% of Mentions (Carrefour, Action, Ikea, Amazon, Lidl). Their votes divide, and a
   wrong Kind sends a member to the wrong Clusters. Example: Leroy Merlin is stored inside a
   "Cursos e Professores" Cluster, so a DIY query never reaches it.
3. **Clustering.** 761 Clusters, 450 with a single member, 172 with vague labels ("Outros (49)",
   "Restaurantes e Bares (4)"), plus catch-alls (largest 131 and 96 members). Clustering is a
   leader algorithm on Item + Context embeddings with one global cutoff (0.5, chosen only because
   it maximised recall on the tune split). It can not separate fondue from sushi inside "Restaurantes
   e Bares", and it scatters one business over unrelated small Clusters.
4. **Retrieval and ranking.** Search is Cluster-first, then pools members. The member rank comes from
   Cluster rank, not from how well a member matches the query, so two different restaurant queries
   return almost the same 20 names. Ranking uses raw 👍-👎 (the 2-year half-weight is applied only at
   ingestion). Result: low precision (0.43) and 12% of expected names cut by the cap.
5. **Answer.** On the held-out run, 6 of 44 questions were routed to plain Q&A by the intent
   classifier (they asked about "sites/plataformas", not "who/where"), and the one-line context is the
   stored Items, which is often "comida" or "não especificado". Pass rate also fluctuates +-0.2
   between runs.

Not a problem: extraction recall over the sampled Threads (95% of expected names are stored). Note
the expected names come from the same Mentions, so this number is optimistic.

## Proposal (in order of expected value for cost)

1. **Member-level retrieval instead of Cluster-first.** Embed and index each *Suggestion* (name +
   Kind keywords + Items + Context) as its own point, and keep Clusters only as grouping and summary
   for the answer. Query -> top members directly, ranked by relevance x community score. This fixes
   losses 4 (cluster not retrieved), the "same list for every query" effect, and most of the member
   cap loss. Needs a loader change and a rebuild, no new LLM cost.
2. **A quality gate at the Suggestion level.** One cheap LLM pass per distinct Suggestion
   (about 2,000 calls) classifying: real named business / generic / app-platform / person / public
   body, plus a Kind check. Drop everything but real businesses (and re-Kind the wrong ones). Expect
   to remove about 40% of the collection, which is the main precision gain. Run it as a measured
   step with the same prompt as in this diagnosis, then check a sample by hand.
3. **One Kind per Suggestion.** Assign the Kind once per business (majority of its Mentions, or by
   the quality-gate pass) so Carrefour/Action/Ikea stop splitting and members stop landing in
   unrelated Clusters.
4. **Better Clusters.** Only needed after 1-3: cluster by purpose with a per-Kind cutoff, merge
   Clusters with fewer than 3 members into the Kind's general one, and generate labels from the Items
   (not "Outros (N)"). With member-level retrieval, Cluster quality stops being critical for recall.
5. **Weighted score at query time.** Store the half-life weighted score per member at ingestion and
   rank by it (closes the PRD gap noted in ADR 0002).
6. **Answer step.** Intent: treat "sites/plataformas/onde/qual" requests for a thing as
   recommendations when a Suggestions hit exists (retrieve first, then decide). Context line: use the
   Mention Context sentence (already extracted, now unused) instead of the raw Items.

## How to validate

Same rules as before: decide on the tune split only, report holdout once. Add two cheap metrics next
to recall: precision of shown members (LLM proxy, as above) and share of non-business members in the
collection (sample of 200, as above). Targets worth stating up front: non-business share under 15%,
member precision above 0.65, tune recall_shown not below 0.64, holdout reported once, and the regression
gate (15 procedural cases) still green.

## Caveats

- The proxy judge and the labels are LLM output; re-check on a hand-labelled sample (issue #58).
- The tune split is 25 questions (88 names), so single percentages move a lot with 1-2 questions.
- Several proposals reuse the same pseudo-golden data that produced the diagnosis. Expect optimism.
