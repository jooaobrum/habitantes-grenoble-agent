# Jev value calibration: which gating method is best?

Follow-up to the feasibility POC. Question: how should Jev's `value`
probabilities be turned into an ingest / don't-ingest decision (and
HIGH / MEDIUM / LOW buckets)?

## Setup

- **Sample:** 120 Q&A pairs, 60 from each chat export
  (`chat-21022026-18072026`, `chat-19012021-20022026`), 20 per heuristic
  tier per export. All extracted with the production parser and pairing code.
- **Jev:** `~typesafe/jev-latest`, `value` question, full probability vector
  kept. No call failed.
- **Ground truth:** three blind Claude judges (40 items each) labelled
  HIGH/MEDIUM/LOW/UNKNOWN from the text only, using the POC rubric. They saw
  neither the heuristic nor Jev output. Single rater, one pass.
- **Judge distribution:** LOW 78, MEDIUM 38, HIGH 4, UNKNOWN 0.

"Ingest" means HIGH or MEDIUM, which is what the pipeline synthesizes and loads.

## Results

| Method | 3-class accuracy | Ingest precision | Ingest recall | Ingest F1 | Pairs ingested |
|---|---|---|---|---|---|
| Heuristic tier | 0.47 | 0.49 | 0.93 | 0.64 | 80 |
| Jev, confidence gate 0.6 (UNKNOWN below) | 0.59 | 0.74 | 0.55 | 0.63 | 31 |
| **Jev argmax / P(HIGH+MEDIUM) ≥ 0.5** | **0.78** | 0.67 | 0.90 | **0.77** | 57 |

Sweep of the ingest threshold on P(HIGH)+P(MEDIUM):

| Threshold | Precision | Recall | F1 | Ingested |
|---|---|---|---|---|
| 0.4 | 0.63 | 0.93 | 0.75 | 62 |
| 0.5 | 0.67 | 0.90 | 0.77 | 57 |
| 0.55 | 0.68 | 0.90 | **0.78** | 56 |
| 0.6 | 0.68 | 0.81 | 0.74 | 50 |
| 0.7 | 0.73 | 0.71 | 0.72 | 41 |
| 0.8 | 0.74 | 0.55 | 0.63 | 31 |

F1 is flat between 0.4 and 0.65. Raising the threshold trades recall for
precision roughly one-for-one.

## Findings

1. **The confidence gate is the worst Jev method.** It loses 35 points of
   recall (0.90 to 0.55) for 7 points of precision. Jev's `confidence` mostly
   measures how split it is between HIGH and MEDIUM, and that split is
   irrelevant to the ingest decision. The POC's "below 0.6 is a coin flip"
   finding held for the 3-class label, not for ingest-or-not.
2. **Bucketing the probabilities is better.** Deciding on P(HIGH)+P(MEDIUM)
   raises 3-class accuracy from 0.59 to 0.78 and ingest F1 from 0.63 to 0.77.
3. **The heuristic ingests almost everything.** It has recall 0.93 but
   precision 0.49: roughly half of what it lets in is LOW.
4. **Tuning does not beat plain argmax.** The best grid cell (0.55) scores
   0.79 in-sample, and 5-fold cross-validated tuning scores 0.69. Argmax needs
   no tuning and scores 0.78, so the extra threshold buys nothing measurable
   at this sample size.
5. **Jev's main error is over-ingestion.** Of 78 judge-LOW pairs, Jev calls 18
   MEDIUM (the false positives), and only 4 of 38 judge-MEDIUM pairs LOW.
6. **HIGH cannot be calibrated from this data.** The judges found only 4 HIGH
   pairs in 120, and Jev predicted HIGH twice. P(HIGH) ≥ 0.3 gives precision
   0.5, recall 0.5 on n=4. There is not enough signal to set a HIGH cut-off.
   Nothing in the pipeline needs the HIGH/MEDIUM split (both are ingested), so
   treat the decision as binary.
7. Results were similar on both exports (argmax accuracy 47/60 on each).

## Recommendation

Replace the confidence gate with a threshold on **P(HIGH)+P(MEDIUM)**,
default **0.6** (config value `jev.ingest_threshold`), chosen as a balance
of recall (0.81) and precision (0.68). 0.5 is the same as taking Jev's argmax
and maximises recall (0.90).
Label the pair HIGH if P(HIGH) ≥ 0.3, else MEDIUM, else LOW. That label is
informational only, because both HIGH and MEDIUM are ingested.

If precision matters more than recall (a smaller, cleaner knowledge base),
raise the threshold to 0.7: precision 0.73, recall 0.71, 41 ingested.

## Caveats

- Single-rater LLM judge. Its rubric is the same one Jev was trained toward,
  so agreement may be flattered.
- n=120, only 4 HIGH. Differences under about 5 points are noise.
- Failed Jev calls are not covered here (none occurred). Those are still
  UNKNOWN and not ingested.
