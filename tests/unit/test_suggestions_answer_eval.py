"""Scoring functions of tests/eval/suggestions_answer_eval.py (fake answers, no LLM)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "eval"))

import suggestions_answer_eval as ev  # noqa: E402

GOOD = (
    "Resumo das principais indicações da comunidade:\n"
    "- **Dr. Martin**: 5👍/0👎, última menção 12/03/2025. Dentista indicado para clareamento e limpeza.\n"
    "- **Clinique Alpes** [negócio de membro do grupo, divulgação própria]: 3👍/1👎, "
    "última menção 01/02/2025. Atende urgências e crianças.\n"
    "Não é uma lista exaustiva; confirme a disponibilidade e os horários antes de ir."
)
TOOL = (
    "Grupo: Dentistas (tipo: Dentists) | 8👍/1👎 no grupo | última menção: 2025-03-12\n"
    "- Dr. Martin: 5👍/0👎 | última menção: 2025-03-12 | indicado para: clareamento\n"
    "- Clinique Alpes [negócio de membro do grupo — divulgação própria]: 3👍/1👎 | "
    "última menção: 2025-02-01 | indicado para: urgências"
)
CASE = {
    "question": "Indicação de dentista?",
    "expected": ["Dr Martin", "Dr Inexistente"],
}


def test_good_answer_passes():
    s = ev.score_case(CASE, GOOD, [TOOL], [TOOL])
    assert s["hit"] and s["coverage"] == 0.5
    assert s["structural_ok"], s["checks"]
    assert s["hallucinations"] == []
    assert s["passed"]


def test_hallucinated_name_is_flagged_and_fails():
    bad = (
        GOOD
        + "\n- **Cabinet Fantôme**: 2👍/0👎, 01/01/2025. Ótimo atendimento geral.\n"
    )
    s = ev.score_case(CASE, bad, [TOOL], [TOOL])
    assert s["hallucinations"] == ["Cabinet Fantôme"]
    assert not s["passed"]


def test_name_in_question_is_grounded():
    case = {
        "question": "O que acham do Cabinet Fantôme?",
        "expected": ["Cabinet Fantôme"],
    }
    ans = "- **Cabinet Fantôme**: 2👍/0👎, 01/01/2025. Ótimo atendimento geral."
    assert ev.faithfulness(ans, case["question"], []) == []


def test_missing_counts_date_context():
    ans = "- **Dr. Martin**: ótimo dentista\nResumo; confirme a disponibilidade."
    c = ev.structural_checks(ans)
    assert not c["has_counts"] and not c["has_date"]
    assert c["summary_notice"] and c["availability"]


def test_net_negative_item_fails():
    ans = "- **Lugar X**: 1👍/4👎, 01/01/2025. Pizza e massas variadas."
    assert not ev.structural_checks(ans)["no_net_negative"]


def test_quotes_and_negative_wording_fail():
    assert not ev.structural_checks("Um membro disse que é bom.")["no_quotes"]
    assert not ev.structural_checks('"O atendimento foi muito bom e rápido"')[
        "no_quotes"
    ]
    assert not ev.structural_checks("Tem reclamações sobre o atendimento.")[
        "negatives_counts"
    ]


def test_undisclosed_community_business_fails():
    ans = GOOD.replace("[negócio de membro do grupo, divulgação própria]", "").replace(
        "Não é uma lista", "Não é uma lista"
    )
    members = ev.tool_members([TOOL])
    assert [m["name"] for m in members if m["community"]] == ["Clinique Alpes"]
    assert not ev.structural_checks(ans, members)["disclosure"]
    assert ev.structural_checks(GOOD, members)["disclosure"]


def test_length_bound_and_weird_ask():
    long = "palavra " * (ev.MAX_WORDS + 1)
    assert not ev.structural_checks(long)["short"]
    assert not ev.structural_checks("Qual é o seu telefone?")["no_weird_ask"]
    assert not ev.structural_checks("Quer? Mesmo? Certo?")["no_weird_ask"]


def test_expected_present_uses_names_match_and_text():
    items = ev.parse_items(GOOD)
    assert ev.expected_present(["Dr Martin"], GOOD, items) == ["Dr Martin"]
    assert ev.expected_present(
        ["Clinique des Alpes"], "tente a Clinique Alpes", []
    ) == ["Clinique des Alpes"]


def test_distractor_ok():
    assert ev.distractor_ok("qa", "Procedimento: ...", 0)
    assert not ev.distractor_ok("recommendation", "x", 0)
    assert not ev.distractor_ok("qa", "5👍/0👎", 0)
    assert not ev.distractor_ok("qa", "x", 1)


def test_summarise():
    rows = [
        ev.score_case(CASE, GOOD, [TOOL], [TOOL]),
        ev.score_case(CASE, "nada", [], []),
    ]
    s = ev.summarise(rows)
    assert s["n"] == 2 and s["pass_rate"] == 0.5 and s["hit_rate"] == 0.5


def test_web_fallback_waives_community_format_but_not_the_rest():
    web = "Pesquisei na web: **Fnac** vende notebooks. Confirme a disponibilidade e os horários."
    s = ev.score_case(
        {"question": "notebook?", "expected": ["Fnac"]},
        web,
        [],
        ["Fnac notebooks"],
        ["Fnac notebooks"],
    )
    assert s["structural_ok"] and s["passed"]
    s2 = ev.score_case(
        {"question": "notebook?", "expected": ["Fnac"]}, web, [], ["Fnac"], []
    )
    assert not s2["structural_ok"]  # no web output: nothing waived


def test_url_lines_are_not_candidate_names():
    ans = "- URL: https://x.fr\n- **Mont Vrac**: ótimo"
    assert ev.faithfulness(ans, "q", ["Mont Vrac"]) == []


def test_domains_and_article_headings_are_not_candidate_names():
    ans = (
        "- **leboncoin.fr**: anúncios\n- **O botão de pressão**: dica\n- **Fnac**: loja"
    )
    assert ev.faithfulness(ans, "q", ["Fnac"]) == []
