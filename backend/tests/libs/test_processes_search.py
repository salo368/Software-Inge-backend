"""Unit tests for the filter building of `Processes.search` / `count_search`."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from libs.orm.processes import Processes


def _sql(*conditions) -> str:
    statement = select(Processes.id).where(*conditions)
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    # the driver's paramstyle doubles every literal percent sign
    return sql.replace("%%", "%")


def _bind_values(*conditions) -> list:
    """The values sent to the driver. Unlike the rendered SQL, they do not
    depend on how the dialect/version escapes literals."""
    statement = select(Processes.id).where(*conditions)
    return list(statement.compile(dialect=postgresql.dialect()).params.values())


def test_no_filters_adds_no_conditions():
    assert Processes._list_conditions(None, [], "") == []


def test_bank_and_stage_filters():
    sql = _sql(*Processes._list_conditions(3, ["PAYMENT", "REVIEW"], ""))

    assert "processes.bank_id = 3" in sql
    assert "processes.stage IN ('PAYMENT', 'REVIEW')" in sql
    assert "ILIKE" not in sql


def test_each_word_must_match_some_field():
    sql = _sql(*Processes._list_conditions(None, [], "ana gomez"))

    fields = len(Processes.SEARCH_FIELDS)
    assert sql.count("ILIKE") == 2 * fields
    assert sql.count("'ana%'") == fields
    assert sql.count("'gomez%'") == fields
    # words are ANDed, the fields of one word are ORed
    assert sql.count(") AND (") == 1
    for key in Processes.SEARCH_FIELDS:
        assert f"submitted_form ->> '{key}'" in sql


def test_search_wildcards_are_literal():
    values = _bind_values(*Processes._list_conditions(None, [], "100%"))
    patterns = [v for v in values if "100" in str(v)]  # the rest are the JSON key names

    # one pattern per searchable field, each with the percent escaped
    assert patterns == [r"100\%%"] * len(Processes.SEARCH_FIELDS)


def test_search_word_count_is_capped():
    sql = _sql(*Processes._list_conditions(None, [], " ".join("w" * (i + 1) for i in range(20))))

    assert sql.count("ILIKE") == Processes.MAX_SEARCH_WORDS * len(Processes.SEARCH_FIELDS)
