"""Unit tests for `libs.utils.openapi_docs`, the Lambda that serves a service's generated docs."""
from __future__ import annotations

import json

import pytest

from libs.utils import openapi_docs

_SPEC = {"openapi": "3.0.3", "info": {"title": "cdts-dev-demo", "version": "abc1234"}, "paths": {}}


@pytest.fixture
def spec_file(tmp_path, monkeypatch):
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(_SPEC), encoding="utf-8")
    monkeypatch.setattr(openapi_docs, "_SPEC_PATH", str(path))
    return path


def test_openapi_json_is_served_verbatim(spec_file):
    resp = openapi_docs.handler({"rawPath": "/demo/openapi.json"}, None)

    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "application/json"
    assert json.loads(resp["body"]) == _SPEC


def test_docs_page_is_swagger_ui_pointing_at_the_sibling_spec(spec_file):
    resp = openapi_docs.handler({"rawPath": "/demo/docs"}, None)

    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"].startswith("text/html")
    assert "swagger-ui-bundle.js" in resp["body"]
    assert 'url: "./openapi.json"' in resp["body"]
    assert "<title>cdts-dev-demo</title>" in resp["body"]


def test_trailing_slash_is_tolerated(spec_file):
    assert openapi_docs.handler({"rawPath": "/demo/openapi.json/"}, None)["headers"]["Content-Type"] == "application/json"


def test_missing_spec_is_a_404_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(openapi_docs, "_SPEC_PATH", str(tmp_path / "nope.json"))

    resp = openapi_docs.handler({"rawPath": "/demo/docs"}, None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "docs_not_generated"}


def test_swagger_ui_version_is_pinned():
    assert "@latest" not in openapi_docs._SWAGGER_UI
    assert openapi_docs._SWAGGER_UI.rsplit("@", 1)[1].count(".") == 2
