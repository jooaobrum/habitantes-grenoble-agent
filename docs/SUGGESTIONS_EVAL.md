# Suggestions: extraction evaluation (issue #58)

Measures how well Mention extraction (#52) works before it is trusted, from a
hand-labelled random sample of Threads.

> **Status: PENDING maintainer hand-labelling.** The tooling is ready; no labels
> exist, so no results or tuned values are recorded yet (see the placeholders
> at the end).

This measures **extraction** (are the real Suggestions in the chat found?). The
answer-level comparison (golden `rec-*` cases vs baseline, v1 regression) is in
`tests/eval/EVAL_GUIDE.md`, also pending a real run.

## 1. Draw the sample

```bash
make mentions   # or any run that produced artifacts/<chat>/classified.csv
make labelling-sample
# or: python ingestion/suggestions/labelling.py --n 50 --seed 42 --min-messages 3
```

Writes `artifacts/<chat>/labelling_sample.jsonl` (gitignored): about 50 Threads
drawn with a seeded RNG over the shared Thread splitting (same `thread_id` as
the candidate windows). Threads shorter than `--min-messages` are skipped.
Authors are replaced by thread-local pseudonyms (M1, M2...). Message text is
left as written, so keep the file local.

## 2. Label

One JSON object per line. Fill the empty `suggestions` list:

```json
{"thread_id": 12,
 "messages": [{"idx": 0, "user": "M1", "timestamp": "...", "message": "alguem indica dentista?"},
              {"idx": 1, "user": "M2", "timestamp": "...", "message": "vou no Dr Silva, otimo"}],
 "suggestions": [
   {"name": "Dr Silva", "kind": "Dentists", "polarity": "positive", "evidence": [1]}
 ]}
```

- One entry per real Suggestion: one person's opinion of one business, place or
  product (same rule as the extraction prompt). People, banks, apps and public
  services are not Suggestions.
- `kind`: exactly one of the `Kind` values in
  `api/src/habitantes/domain/suggestions.py`.
- `polarity`: `positive` or `negative` (recorded, not scored yet).
- `evidence`: indices (`idx`) of the message(s) that carry the opinion. Coverage
  counts a Suggestion as covered only when all its evidence messages sit inside
  one candidate window.
- Threads with no Suggestion keep `[]`; they still count toward wrong extractions.
- Label what is in the chat, not what the extractor would find. Do not edit
  `messages`.

Invalid labels (unknown kind, missing or out-of-range evidence) abort the run.

## 3. Measure

```bash
make labelling-measure
# or: python ingestion/suggestions/measure.py --details \
#       --before 5 --after-request 15 --after-other 5
```

Window sizes default to `config/base.yaml` (`suggestions.*`); the flags try
other values without editing the config. The real Jev filter and extraction LLM
run per window, so this needs `OPENROUTER_API_KEY` and costs tokens. Per Kind
and in total it reports:

| Metric | Meaning |
|---|---|
| window coverage | labelled Suggestions inside a candidate window / labelled |
| recall | labelled Suggestions matched by an extracted Mention / labelled |
| wrong | extracted Mentions matching no label / extracted |

Matching: same Kind, names equal or one contained in the other (case, accents
and punctuation ignored). A right name under the wrong Kind is both a miss and a
wrong extraction. `--details` lists the uncovered, missed and wrong items. The
lexicon lives in `ingestion/suggestions/windows.py` (`REQUEST_PATTERNS`,
`OTHER_PATTERNS`).

Logic is unit-tested with a fake extractor on a tiny fixture:
`tests/unit/test_suggestions_measure.py`.

## 4. Tuned values (PENDING maintainer labelling)

| Setting | Current | Tuned |
|---|---|---|
| `window_before` | 5 | pending |
| `window_after_request` | 15 | pending |
| `window_after_other` | 5 | pending |
| `jev_cutoff` | 0.5 | pending |
| Lexicon changes | none | pending |

Baseline results (sample size, seed, per-Kind coverage/recall/wrong): pending.

## 5. Fall back to scanning every message? (PENDING)

Decision to record once labelled: how many labelled Suggestions fall outside
every window (the "Outside every window" line of the report), and whether that
share justifies sending every message of a Thread to extraction instead of only
windows (higher cost, better coverage). Threshold and decision: pending.
