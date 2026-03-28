"""Tests for _parse_sector() — the multi-sector string parser."""
import pytest

from backend.scoring.dual_scorer import _parse_sector


class TestParseSector:
    """All storage formats must be handled correctly."""

    def test_none_returns_empty(self):
        assert _parse_sector(None) == []

    def test_nan_returns_empty(self):
        import math
        assert _parse_sector(float("nan")) == []

    def test_empty_string_returns_empty(self):
        assert _parse_sector("") == []

    def test_single_string(self):
        assert _parse_sector("tech") == ["tech"]

    def test_json_list(self):
        assert _parse_sector('["healthcare", "tech"]') == ["healthcare", "tech"]

    def test_python_repr_list(self):
        assert _parse_sector("['healthcare', 'tech']") == ["healthcare", "tech"]

    def test_three_sector_json(self):
        assert _parse_sector('["defense", "energy", "healthcare"]') == ["defense", "energy", "healthcare"]

    def test_three_sector_repr(self):
        assert _parse_sector("['defense', 'energy', 'healthcare']") == ["defense", "energy", "healthcare"]

    def test_already_list(self):
        assert _parse_sector(["healthcare", "tech"]) == ["healthcare", "tech"]

    def test_single_element_list(self):
        assert _parse_sector(["tech"]) == ["tech"]

    def test_whitespace_handling(self):
        assert _parse_sector("  tech  ") == ["tech"]

    def test_json_with_spaces(self):
        assert _parse_sector(' ["healthcare" , "tech"] ') == ["healthcare", "tech"]

    def test_all_seven_sectors_single(self):
        """Each of the 7 sectors must round-trip correctly."""
        for sector in ["defense", "finance", "healthcare", "energy", "tech", "telecom", "agriculture"]:
            assert _parse_sector(sector) == [sector]
