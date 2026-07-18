"""Held-out generalization probe template — see tests/eval/EVAL_GUIDE.md step 5.

Purpose: after a prompt fix targets specific failing golden-dataset cases, check the
fix generalizes to genuinely new questions (same underlying trigger, different topic/
wording) instead of having been memorized to the dataset's specific facts/phrasing.
None of the questions below are in golden_dataset_v2.json.

USAGE: before your next round, replace PROBES with questions relevant to whatever
you just changed — same triggers/categories you're targeting, different concrete
topics than any golden_dataset_v2.json case, plus 1-2 distractors that should NOT
trigger the new behavior (to catch over-triggering). Run once against the prompt
BEFORE your change (git stash it) and once AFTER, and diff the two by hand — a real
fix should look better on both; a memorized one will only look better on cases that
resemble the exact training examples.

The PROBES below are this round's (2026-07) concrete example — kept as a worked
reference, not because they need to be rerun verbatim next time.
"""

import sys

sys.path.insert(0, "api/src")
import uuid
from habitantes.domain import agent as agent_mod

PROBES = [
    (
        "money-promo (held-out: Revolut, not Boursorama)",
        "Ainda vale a pena pegar link de indicação pro Revolut? Tem algum bônus rolando agora?",
    ),
    (
        "transport-schedule (held-out: Lyon airport FlixBus, not Ouigo Paris)",
        "Ainda tem ônibus FlixBus saindo praticamente de hora em hora do aeroporto de Lyon Saint-Exupéry pra Grenoble?",
    ),
    (
        "visa-document (held-out: OFII exam requirement, not passport talent)",
        "No exame do OFII pra validar o visto, ainda é obrigatório fazer raio-x de pulmão?",
    ),
    (
        "factual-web (held-out: mayor, not population/SMIC/tram)",
        "Quem é o prefeito de Grenoble atualmente?",
    ),
    (
        "distractor: price with no official source (should NOT be crippled by web guardrail)",
        "Quanto custa em média um corte de cabelo masculino num salão aqui em Grenoble?",
    ),
    (
        "distractor: out-of-scope, casual phrasing",
        "Qual é a previsão do tempo pra virada do ano em Copacabana?",
    ),
]

for label, question in PROBES:
    state = agent_mod.run(
        chat_id=f"probe-{uuid.uuid4().hex[:8]}",
        message=question,
        message_id=uuid.uuid4().hex,
        trace_id=uuid.uuid4().hex,
    )
    sources = state.get("sources", [])
    web_used = any(s.get("category") == "Web (Grenoble)" for s in sources)
    print("=" * 90)
    print(f"[{label}]")
    print(f"Q: {question}")
    print(f"web_used={web_used}  intent={state.get('intent')}")
    print(f"A: {state.get('answer', '')[:600]}")
    print()
