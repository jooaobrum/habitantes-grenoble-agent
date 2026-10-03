from ingestion.suggestions.name_groups import compact_key, group_names, is_generic


def _same(groups, a, b):
    return any(a in g and b in g for g in groups)


def test_spelling_type_word_and_token_subset_variants_are_grouped():
    names = [
        "Natal", "Restaurante Natal", "O Natal", "Café/Restaurante Natal", "Natal Grenoble",
        "Come Prima", "Pizzeria Come Prima", "Comeprima",
        "Barrio Latino", "Barril Latino", "Casa Barriolatino", "Bairro Latino",
        "Yamato", "Yamato Ramen",
        "Chez Marius", "Ferme à Dédé",
    ]  # fmt: skip
    groups, _, _ = group_names(names)
    assert _same(groups, "Natal", "Restaurante Natal")
    assert _same(groups, "Natal", "O Natal")
    assert _same(groups, "Natal", "Natal Grenoble")
    assert _same(groups, "Come Prima", "Pizzeria Come Prima")
    assert _same(groups, "Come Prima", "Comeprima")
    assert _same(groups, "Barrio Latino", "Casa Barriolatino")
    assert _same(groups, "Barrio Latino", "Barril Latino")
    assert _same(groups, "Yamato", "Yamato Ramen")
    assert not _same(groups, "Chez Marius", "Ferme à Dédé")
    assert not _same(groups, "Natal", "Come Prima")


def test_places_that_only_share_a_cuisine_or_city_stay_apart():
    names = [
        "Tacos de Grenoble",
        "Tacos de Lyon",
        "Kabuki Canton",
        "Katana",
        "Snack Brasil",
        "DoBrazil",
    ]
    groups, _, _ = group_names(names)
    assert not _same(groups, "Tacos de Grenoble", "Tacos de Lyon")
    assert not _same(groups, "Kabuki Canton", "Katana")
    assert not _same(groups, "Snack Brasil", "DoBrazil")


def test_generic_names_are_not_assigned_to_any_group():
    groups, generic, _ = group_names(
        ["Natal", "Restaurante brasileiro", "Pizzeria", "bar"]
    )
    assert set(generic) == {"Restaurante brasileiro", "Pizzeria", "bar"}
    assert all("Restaurante brasileiro" not in g for g in groups)
    assert is_generic("Restaurante Brasileiro") and not is_generic("Natal")


def test_compact_key_ignores_spacing_and_type_words():
    assert compact_key("Casa Barrio Latino") == compact_key("barriolatino")


def test_short_name_inside_two_places_is_a_suggestion_not_a_bridge():
    names = ["Come Prima", "Come M14ma", "Come Va", "Kabuki", "Kabuki Canton"]
    groups, _, suggestions = group_names(names)
    assert not _same(groups, "Come Prima", "Come Va")
    assert not _same(groups, "Come Prima", "Come M14ma")
    assert not _same(groups, "Kabuki", "Kabuki Canton")  # reviewed, not applied
    assert ("Kabuki", "Kabuki Canton") in suggestions
