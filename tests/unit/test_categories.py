"""Unit tests for domain/categories.py pure helpers."""

from habitantes.config import CategoryEntry
from habitantes.domain.categories import (
    build_greeting_text,
    get_by_en_name,
    resolve_number,
)

_CATS = [
    CategoryEntry(pt_name="Visto & Residência", en_name="Visa & Residency"),
    CategoryEntry(pt_name="Bancos & Finanças", en_name="Banking & Finance"),
    CategoryEntry(pt_name="Moradia & CAF", en_name="Housing & CAF"),
]


class TestResolveNumber:
    def test_valid_number_returns_entry(self):
        assert resolve_number("1", _CATS).en_name == "Visa & Residency"

    def test_valid_number_boundary(self):
        assert resolve_number("3", _CATS).en_name == "Housing & CAF"

    def test_out_of_range_returns_none(self):
        assert resolve_number("4", _CATS) is None

    def test_zero_returns_none(self):
        assert resolve_number("0", _CATS) is None

    def test_text_returns_none(self):
        assert resolve_number("visto", _CATS) is None

    def test_number_with_whitespace(self):
        assert resolve_number("  2  ", _CATS).en_name == "Banking & Finance"

    def test_float_string_returns_none(self):
        assert resolve_number("1.5", _CATS) is None


class TestGetByEnName:
    def test_found(self):
        entry = get_by_en_name("Banking & Finance", _CATS)
        assert entry is not None
        assert entry.pt_name == "Bancos & Finanças"

    def test_not_found_returns_none(self):
        assert get_by_en_name("Unknown Category", _CATS) is None


class TestBuildGreetingText:
    def test_contains_numbered_categories(self):
        text = build_greeting_text(_CATS)
        assert "1." in text
        assert "Visto & Residência" in text
        assert "2." in text
        assert "Bancos & Finanças" in text

    def test_contains_header(self):
        text = build_greeting_text(_CATS)
        assert "Habitantes de Grenoble" in text

    def test_contains_call_to_action(self):
        text = build_greeting_text(_CATS)
        assert "Digite" in text

    def test_empty_categories_still_renders(self):
        text = build_greeting_text([])
        assert "Habitantes de Grenoble" in text
