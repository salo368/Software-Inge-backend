"""Unit tests for `libs.orm.like.prefix_pattern`."""
from __future__ import annotations

import pytest

from libs.orm.like import prefix_pattern


@pytest.mark.parametrize(
    "term, pattern",
    [
        ("ana", "ana%"),
        ("", "%"),
        ("a_b", r"a\_b%"),
        ("100%", r"100\%%"),
        ("a\\b", r"a\\b%"),
        ("a_b%\\c", r"a\_b\%\\c%"),
    ],
)
def test_prefix_pattern_escapes_wildcards(term, pattern):
    assert prefix_pattern(term) == pattern
