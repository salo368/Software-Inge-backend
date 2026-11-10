"""Unit tests for `libs.utils.params`."""
from __future__ import annotations

import json
from uuid import UUID

import pytest

from libs.core.responses import HandledError
from libs.utils.params import request_params, uuid_param

_ID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def test_request_params_reads_query_string():
    assert request_params({"queryStringParameters": {"a": "1"}}) == {"a": "1"}


def test_request_params_reads_body():
    assert request_params({"body": json.dumps({"a": 1})}) == {"a": 1}


def test_request_params_body_wins_over_query():
    event = {"queryStringParameters": {"a": "q", "b": "q"}, "body": json.dumps({"a": "body"})}

    assert request_params(event) == {"a": "body", "b": "q"}


def test_request_params_empty():
    assert request_params({}) == {}
    assert request_params({"queryStringParameters": None, "body": None}) == {}


def test_request_params_invalid_json_is_400():
    with pytest.raises(HandledError) as e:
        request_params({"body": "{nope"})

    assert (e.value.message, e.value.status_code) == ("invalid_json_body", 400)


def test_request_params_ignores_non_object_body():
    assert request_params({"body": json.dumps([1, 2])}) == {}


def test_uuid_param():
    assert uuid_param({"id": _ID}, "id", "bad") == UUID(_ID)


@pytest.mark.parametrize("params", [{}, {"id": None}, {"id": "nope"}, {"id": 5}])
def test_uuid_param_invalid(params):
    with pytest.raises(HandledError) as e:
        uuid_param(params, "id", "bad")

    assert (e.value.message, e.value.status_code) == ("bad", 400)


# --- pagination ---


def test_pagination_defaults():
    from libs.utils.params import pagination_params

    assert pagination_params({}) == (20, 0)


def test_pagination_offset():
    from libs.utils.params import pagination_params

    assert pagination_params({"page": "3", "page_size": 10}) == (10, 20)


@pytest.mark.parametrize(
    "params, error",
    [
        ({"page": 0}, "invalid_page"),
        ({"page": "x"}, "invalid_page"),
        ({"page_size": 0}, "invalid_page_size"),
        ({"page_size": 101}, "invalid_page_size"),
    ],
)
def test_pagination_invalid(params, error):
    from libs.utils.params import pagination_params

    with pytest.raises(HandledError) as e:
        pagination_params(params)

    assert (e.value.message, e.value.status_code) == (error, 400)


def test_paginated_response_shape():
    from libs.utils.params import paginated_response

    assert paginated_response(["a", "b"], 10, 20, 45) == {
        "results": ["a", "b"], "count": 2, "pagination": {"offset": 20, "limit": 10, "total": 45},
    }
