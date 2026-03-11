---
name: domain-discovery-ddd
version: "1.0"
last_reviewed: "2025-01"
description: Run strategic domain discovery (DDD strategic first) for a data science / agentic system. Produces ubiquitous language, bounded contexts, core domain, domain rules, and the MVP workflow boundary. Use at ideation-to-spec bootstrap and when scope is unclear. Not for code implementation.
---

# Domain Discovery (DDD Strategic First) — DS / Agentic

## Why this skill exists
Teams often jump into "tactical" structure (folders, services, entities) before clarifying the domain.
This skill forces **strategic clarity first**: vocabulary, boundaries, and what matters for the MVP.

## Inputs
- `docs/ideation/ideation-brief.md`
- Any existing domain docs or datasets (optional)

## Outputs (write to docs/)
Create or update:
- `docs/domain/ubiquitous-language.md` (create if missing)
- `docs/domain/bounded-contexts.md` (create if missing)
- `docs/domain/domain-rules.md` (create if missing)
- Update `.specs/project/STATE.md` and `.specs/features/mvp/spec.md` if needed.

## Process (lightweight)
1) **Ubiquitous language (10–20 terms)**
   - Term → definition → example
   - Include: what users say vs what system stores
2) **Bounded contexts**
   - Identify 2–5 contexts (e.g., Operations, Maintenance, Knowledge Base, Monitoring)
   - For each: responsibilities, key data, key metrics, interfaces
   - Pick the MVP context(s)
3) **Core domain + supporting domains**
   - Core: what differentiates the solution
   - Supporting: generic/commodity parts
4) **Domain rules**
   - Business constraints, safety constraints, compliance constraints
   - “Never do X” rules for the agent
5) **Map to agent workflow**
   - Confirm what belongs in: UI / API / Graph / Tools / Ingestion
   - Confirm what facts must come from tools (not the LLM)
6) **MVP cut**
   - “In” vs “Out”
   - Top 5 failure modes + expected safe behaviors

## Guardrails (avoid overengineering)
- Do not create domain-specific custom agents. Prefer skills + docs.
- Keep contexts few and stable.
- Keep outputs short and used by specs.

## Output format (mandatory)
- Files created/updated
- Ubiquitous language (10–20 terms)
- Bounded contexts list + MVP selection
- Domain rules (bullets)
- Spec impacts (what to update in spec/design)
