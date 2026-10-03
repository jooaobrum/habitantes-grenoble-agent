# 0003 — Transport and Housing Kinds

Status: accepted (deviates from PRD #49, which fixes 14 Kinds)

## Context

The first real run (6,848 Mentions from the 2021-2026 export) showed groups of businesses that
did not fit any of the 14 Kinds:

- Airlines, trains, coaches, carpooling and car/bike rental (FlixBus, TAP, Air France, TAG, LATAM,
  BlaBlaCar, Getaround, Metrovelo, SNCF/TGV/TER) were spread over Other, Places & Outings and
  Professional Services.
- CROUS appears both as the university restaurant and as the student housing provider; the housing
  Mentions were filed under Professional Services or Places & Outings.
- Student residences, flatshare listings and housing platforms (Résidence Houille Blanche, carte des
  colocs, Seloger, Airbnb) had no Kind.

## Decision

Add two Kinds: **Transport** (Topic "Travel & Transport") and **Housing** (Topic "Housing & CAF").
Both Topics already exist in the menu. The Kind→Topic mapping stays fixed and one-to-one per Kind.

The extraction prompt builds its Kind list from the enum, so new extractions can use them. The
existing 6,848 Mentions were not re-extracted: their raw `kind` is kept, and the name-grouping step
assigns `group_kind` through `config/suggestion_name_aliases.yaml` (`kinds:` for named businesses,
`split:` for CROUS). A business seen under several Kinds takes the Kind with most Mentions.

## Consequences

- PRD #49, README and CONTEXT.md list 16 Kinds, not 14. Documents were updated.
- The Suggestions collection loaded before this change still uses the old raw Kinds; it changes
  at the next rebuild from `grouped_mentions.jsonl`.
- The alias file is hand-maintained; a new Transport or Housing business not listed there keeps
  its extracted Kind until the next extraction run picks the new Kind by itself.
