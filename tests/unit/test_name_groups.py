from datetime import date

from ingestion.suggestions.extract import Mention
from ingestion.suggestions.name_groups import (
    Aliases,
    compact_key,
    group_mentions,
    group_names,
    is_generic,
    load_aliases,
)
from ingestion.suggestions.merge import normalise_name


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


def _aliases():
    return load_aliases()  # the real manual decisions in config/


def test_manual_same_and_separate_decisions_from_config():
    names = [
        "Kabuki", "Kabuki Canton", "Bombay", "Bombay Talkies", "O'Callaghan", "O'Callaghan Irish Pub",
        "Diderot", "CROUS", "RU Intermezzo", "Resto Universitaires", "CROUS da Le Home",
        "Bairro Latino", "Barrio Latino", "Barril Latino", "Casa Barriolatino",
        "Come Va", "Come Prima", "Chez Marius", "Bouillon Archers Chez Marius",
    ]  # fmt: skip
    groups, generic, _ = group_names(names, _aliases())
    assert _same(groups, "Kabuki", "Kabuki Canton")
    assert _same(groups, "Bombay", "Bombay Talkies")
    assert _same(groups, "O'Callaghan", "O'Callaghan Irish Pub")
    assert _same(groups, "Diderot", "CROUS")
    assert _same(groups, "CROUS", "RU Intermezzo")
    assert _same(groups, "CROUS", "Resto Universitaires")
    assert _same(groups, "Barrio Latino", "Casa Barriolatino")
    assert _same(
        groups, "Bairro Latino", "Casa Barriolatino"
    )  # all spellings: one business
    assert _same(groups, "Barril Latino", "Casa Barriolatino")
    assert not _same(groups, "Come Va", "Come Prima")
    assert not _same(groups, "Chez Marius", "Bouillon Archers Chez Marius")
    assert generic == []  # "Bairro Latino" and the RU names are valid names


def _m(name, kind="Restaurants & Bars", polarity="positive"):
    return Mention(
        name=name, kind=kind, polarity=polarity, items=[], context="x",
        date=date(2025, 1, 1), community_business=False,
    )  # fmt: skip


def test_group_mentions_keeps_raw_name_and_adds_group_and_drops_generic_names():
    ms = [
        _m("Natal"),
        _m("Natal"),
        _m("Restaurante Natal", polarity="negative"),
        _m("Restaurante brasileiro"),
        _m("Pizzeria"),
        _m("Chez Marius"),
    ]
    grouped, report = group_mentions(ms, Aliases())
    assert [g.name for g in grouped] == [
        "Natal",
        "Natal",
        "Restaurante Natal",
        "Chez Marius",
    ]  # raw
    assert [g.group for g in grouped] == [
        "Natal",
        "Natal",
        "Natal",
        "Chez Marius",
    ]  # single: group = name
    assert sum(g.polarity == "negative" for g in grouped if g.group == "Natal") == 1
    assert {d["name"] for d in report["dropped_generic"]} == {
        "Restaurante brasileiro",
        "Pizzeria",
    }
    assert report["kinds"]["Restaurants & Bars"]["dropped_generic"] == 2


def test_group_mentions_runs_on_every_kind():
    ms = [
        _m("Dr Silva", kind="Dentists"),
        _m("Dr. Silva", kind="Dentists"),
        _m("Action", kind="Shops"),
    ]
    grouped, report = group_mentions(ms, Aliases())
    assert {g.kind.value for g in grouped} == {"Dentists", "Shops"}
    assert set(report["kinds"]) == {"Dentists", "Shops"}


def test_short_brands_need_mentions_and_keep_list_exempts_generic_looking_names():
    names = [
        "B&M",
        "B & M",
        "F1",
        "Snack Brasil",
        "Restaurante brasileiro",
        "Natal",
        "Pizza Hut",
        "168",
        "Brasil",
    ]
    counts = {
        "B&M": 20,
        "B & M": 2,
        "F1": 1,
        "Snack Brasil": 4,
        "Restaurante brasileiro": 4,
        "Natal": 9,
        "Pizza Hut": 1,
        "168": 2,
        "Brasil": 3,
    }
    aliases = Aliases(keep=frozenset({normalise_name("Snack Brasil")}))
    groups, generic, _ = group_names(names, aliases, counts)
    assert _same(groups, "B&M", "B & M")
    assert set(generic) == {
        "F1",
        "Restaurante brasileiro",
        "168",
        "Brasil",
    }  # Pizza Hut stays; keep is exact, not by key
    assert any("Snack Brasil" in g for g in groups)


def test_names_with_no_distinctive_word_never_merge_with_each_other():
    aliases = Aliases(keep=frozenset({"snack brasil", "tacos", "pizza 51"}))
    names = ["Snack Brasil", "Tacos", "Pizza 51", "Thai Express"]
    groups, _, _ = group_names(names, aliases)
    assert not _same(groups, "Snack Brasil", "Tacos")
    assert not _same(groups, "Tacos", "Thai Express")


def test_shared_city_suffix_and_conflicting_qualifiers_do_not_merge():
    names = ["TER Grenoble", "Pathé Grenoble", "Consulado de Paris",
             "Consulado Italiano de Grenoble", "CHU de Grenoble", "CHU Grenoble", "Leclerc", "Leclerc Échirolles"]  # fmt: skip
    groups, _, _ = group_names(names)
    assert not _same(groups, "TER Grenoble", "Pathé Grenoble")
    assert not _same(groups, "Consulado de Paris", "Consulado Italiano de Grenoble")
    assert _same(groups, "CHU de Grenoble", "CHU Grenoble")
    assert _same(groups, "Leclerc", "Leclerc Échirolles")


def test_generic_category_nouns_are_dropped():
    _, generic, _ = group_names(
        ["Ótica", "Mercado", "açougue", "Ginecologista", "Comida", "Action"]
    )
    assert set(generic) == {"Ótica", "Mercado", "açougue", "Ginecologista", "Comida"}


def test_real_businesses_with_generic_looking_names_survive_via_aliases():
    names = ["Medecin 7/7", "médecin 7/7", "Médecins 7/7", "U", "Dentista", "Ótica"]
    groups, generic, _ = group_names(names, load_aliases(), {n: 1 for n in names})
    assert _same(groups, "Medecin 7/7", "Médecins 7/7")
    assert _same(groups, "médecin 7/7", "Médecins 7/7")
    assert any("U" in g for g in groups)
    assert set(generic) == {"Dentista", "Ótica"}


def test_business_under_several_kinds_takes_the_kind_with_most_mentions_and_keeps_raw_kind():
    ms = [_m("Carrefour", kind="Markets & Groceries")] * 3 + [
        _m("Carrefour", kind="Shops"),
        _m("carrefour", kind="Shops"),
        _m("Action", kind="Shops"),
    ]
    grouped, report = group_mentions(ms, Aliases())
    carrefour = [g for g in grouped if g.name.lower() == "carrefour"]
    assert {g.group for g in carrefour} == {"Carrefour"}
    assert {g.group_kind.value for g in carrefour} == {"Markets & Groceries"}
    assert {g.kind.value for g in carrefour} == {
        "Markets & Groceries",
        "Shops",
    }  # raw kept
    assert [g.group_kind.value for g in grouped if g.name == "Action"] == ["Shops"]
    assert report["rekinded"][0]["group"] == "Carrefour"
    assert report["rekinded"][0]["kinds"] == {"Markets & Groceries": 3, "Shops": 2}


def test_kind_ties_prefer_specific_kinds_and_alias_can_fix_the_kind():
    ms = [_m("Vieux Manoir", kind="Restaurants & Bars")] * 3 + [
        _m("Vieux Manoir", kind="Places & Outings")
    ] * 3
    grouped, _ = group_mentions(ms, Aliases())
    assert {g.group_kind.value for g in grouped} == {
        "Restaurants & Bars"
    }  # tie -> specific Kind
    ms = [_m("CROUS", kind="Places & Outings")] * 5 + [
        _m("CROUS", kind="Restaurants & Bars")
    ] * 2
    grouped, _ = group_mentions(ms, load_aliases())
    assert {g.group_kind.value for g in grouped} == {
        "Restaurants & Bars"
    }  # alias kind wins


def test_kinds_community_and_split_decisions_from_config():
    ms = [
        _m("FlixBus", kind="Other"),
        _m("Chez Pamella", kind="Other"),
        _m("TER Grenoble", kind="Places & Outings"),
        _m("TER", kind="Other"),
        _m("CHU de Grenoble", kind="Doctors"),
        _m("CHU Sud", kind="Doctors"),
        _m("Hôpital Sud", kind="Doctors"),
        _m("La Tronche", kind="Doctors"),
    ]
    grouped, _ = group_mentions(ms, load_aliases())
    by = {g.name: g for g in grouped}
    assert (
        by["FlixBus"].group_kind.value == "Transport"
        and by["FlixBus"].kind.value == "Other"
    )
    assert by["Chez Pamella"].group_kind.value == "Restaurants & Bars"
    assert by["Chez Pamella"].group_community_business is True
    assert by["FlixBus"].group_community_business is False
    assert by["TER Grenoble"].group == by["TER"].group == "TER"
    assert by["TER Grenoble"].group_kind.value == "Transport"
    assert {
        by[n].group for n in ("CHU de Grenoble", "CHU Sud", "Hôpital Sud", "La Tronche")
    } == {"CHU Grenoble Alpes"}


def _c(name, items, context, kind="Professional Services"):
    return Mention(
        name=name, kind=kind, polarity="positive", items=items, context=context,
        date=date(2025, 1, 1), community_business=False,
    )  # fmt: skip


def test_crous_is_split_into_restaurant_and_housing_by_what_the_mention_says():
    ms = [
        _c("CROUS", ["almoço"], "O almoço no CROUS custou 7 euros."),
        _c("Crous", ["alojamento estudantil"], "O alojamento estudantil nacional é bom."),
        _c("RU Minatec", [], "Servia opção vegetariana."),
        _c("Diderot", [], "Restaurante ótimo."),
        _c("CROUS", [], "Cuidado com os prazos do CROUS.", kind="Professional Services"),
    ]  # fmt: skip
    grouped, _ = group_mentions(ms, load_aliases())
    got = [(g.group, g.group_kind.value) for g in grouped]
    assert got[0] == ("CROUS (restaurante universitário)", "Restaurants & Bars")
    assert got[1] == ("CROUS (alojamento)", "Housing")
    assert got[2][1] == got[3][1] == "Restaurants & Bars"
    assert got[4] == (
        "CROUS (restaurante universitário)",
        "Restaurants & Bars",
    )  # default
