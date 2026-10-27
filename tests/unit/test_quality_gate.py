from ingestion.suggestions.quality_gate import (
    build_groups,
    questions_for,
    decide,
    gate_metrics,
    pick_cutoff,
)


def _row(group, name, polarity="positive", kind="Shops", items=(), context="ok"):
    return {"group": group, "name": name, "polarity": polarity, "kind": kind,
            "items": list(items), "context": context}  # fmt: skip


def test_build_groups_collects_variants_counts_items_and_positive_contexts():
    rows = [
        _row("Natal", "Natal", items=["açaí"], context="Ótimo açaí."),
        _row("Natal", "Restaurante Natal", items=["açaí", "coxinha"], context="Bom."),
        _row("Natal", "Natal", polarity="negative", context="Caro."),
        _row("Zé", "Zé"),
    ]
    g = {x.group: x for x in build_groups(rows)}
    assert g["Natal"].mentions == 3 and (
        g["Natal"].thumbs_up,
        g["Natal"].thumbs_down,
    ) == (2, 1)
    assert (
        g["Natal"].variants[0] == "Natal" and "Restaurante Natal" in g["Natal"].variants
    )
    assert g["Natal"].items[0] == "açaí"
    assert (
        "Caro." not in g["Natal"].contexts
    )  # a negative opinion is never shown as the pitch
    assert g["Natal"].state()["mentions"] == 3


def test_decide_is_stricter_for_single_mention_groups_and_drops_unscored():
    assert decide(0.8, 5, cutoff=0.7, single_cutoff=0.9)
    assert not decide(0.8, 1, cutoff=0.7, single_cutoff=0.9)
    assert decide(0.95, 1, cutoff=0.7, single_cutoff=0.9)
    assert not decide(None, 9, cutoff=0.1, single_cutoff=0.1)


def test_pick_cutoff_is_the_strictest_one_that_keeps_enough_valid_groups():
    rows = [
        (0.95, True),
        (0.9, True),
        (0.85, True),
        (0.6, True),
        (0.5, False),
        (0.2, False),
    ]
    c = pick_cutoff(rows, min_recall=0.75)
    m = gate_metrics(rows, c)
    assert m["recall_valid"] >= 0.75 and m["non_business_share_kept"] == 0.0
    assert pick_cutoff([(0.3, False)]) is None


def test_gate_metrics_reports_kept_share_and_junk_left():
    rows = [(0.9, True), (0.8, False), (0.3, True), (0.1, False)]
    m = gate_metrics(rows, 0.5)
    assert m["kept_share"] == 0.5
    assert m["non_business_share_kept"] == 0.5
    assert m["recall_valid"] == 0.5


def test_apply_gate_keeps_rows_of_kept_groups_untouched():
    from ingestion.suggestions.quality_gate import apply_gate

    rows = [
        _row("Natal", "Natal"), _row("Natal", "O Natal"),
        _row("Livro", "Livro"),
        _row("Zé Bar", "Zé Bar"),
        _row("Sem score", "Sem score"),
    ]  # fmt: skip
    scores = {
        "Natal": {"valid": 0.45},  # 2 mentions -> cutoff 0.4: kept
        "Livro": {"valid": 0.1},
        "Zé Bar": {"valid": 0.45},  # single mention -> stricter 0.5: dropped
    }
    kept, dropped = apply_gate(rows, scores, cutoff=0.4, single_cutoff=0.5)
    assert [r["name"] for r in kept] == ["Natal", "O Natal"]
    assert dropped == ["Livro", "Sem score", "Zé Bar"]


def test_destinations_are_valid_only_for_places_and_outings():
    assert "IS valid" in questions_for("Places & Outings")["valid"]
    assert "IS valid" not in questions_for("Shops")["valid"]
    assert (
        questions_for("Shops")["generic"]
        == questions_for("Places & Outings")["generic"]
    )


def test_named_practitioners_are_valid_for_professional_kinds_only():
    for kind in ("Doctors", "Dentists", "Translators", "Salons & Beauty"):
        assert "practitioner" in questions_for(kind)["valid"]
    for kind in ("Shops", "Restaurants & Bars", "Places & Outings"):
        assert "practitioner" not in questions_for(kind)["valid"]


def test_alias_listed_businesses_are_protected_from_the_gate():
    from ingestion.suggestions.name_groups import load_aliases
    from ingestion.suggestions.quality_gate import apply_gate, protected_keys

    rows = [
        _row("CROUS (alojamento)", "Crous"),
        _row("FlixBus", "FlixBus"),
        _row("Livro", "Livro"),
    ]
    scores = {g: {"valid": 0.05} for g in ("CROUS (alojamento)", "FlixBus", "Livro")}
    kept, dropped = apply_gate(rows, scores, protected=protected_keys(load_aliases()))
    assert [r["group"] for r in kept] == ["CROUS (alojamento)", "FlixBus"]
    assert dropped == ["Livro"]
