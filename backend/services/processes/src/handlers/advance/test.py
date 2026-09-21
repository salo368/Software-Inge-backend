"""Unit tests for the processes/advance Lambda.

Covers the four possible transitions of the process state machine:

    form      -> documents   (snapshot the Forms row)
    documents -> signature   (open a signature ceremony, return sign_url)
    signature -> payment     (require the ceremony to be `signed`)
    payment   -> done        (mocked; no gate)
    done      -> done        (idempotent)

Plus every failure mode along the way. Signature bridge internals are
stubbed here; their own coverage lives under
`tests/services/processes/utils/` for the pure helpers and inside
`services/signatures/**/test.py` for the target handler.
"""
from __future__ import annotations

import json
from uuid import uuid4
from unittest.mock import MagicMock


def _authed_event(pid: str) -> dict:
    return {"headers": {"Authorization": "Bearer tok"}, "pathParameters": {"id": pid}}


def _patch_auth(monkeypatch, user_id="u-1", email="titular@example.com", full_name="Ada"):
    user = MagicMock(id=user_id, email=email, full_name=full_name)
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def _proc(user_id: str, stage: str, *, sign_id=None):
    return MagicMock(
        id=uuid4(),
        user_id=user_id,
        stage=stage,
        form_snapshot=None,
        sign_id=sign_id,
        bank_id=42,
        advance_to=MagicMock(),
        public_dict=MagicMock(return_value={"stage": stage, "sign_id": sign_id}),
    )


# ---------------------------------------------------------------------------
# form -> documents
# ---------------------------------------------------------------------------
class TestFromForm:
    def test_advance_snapshots_form_and_advances(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "form")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
        monkeypatch.setattr(
            h,
            "Forms",
            MagicMock(get_by_user=MagicMock(return_value=MagicMock(
                public_dict=MagicMock(return_value={"full_name": "Foo"})
            ))),
        )

        resp = h.handler(_authed_event(str(uuid4())), None)

        assert resp["statusCode"] == 200
        assert proc.form_snapshot == {"full_name": "Foo"}
        proc.advance_to.assert_called_once_with("documents")

    def test_missing_form_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "form")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
        monkeypatch.setattr(h, "Forms", MagicMock(get_by_user=MagicMock(return_value=None)))

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "form_required"}
        proc.advance_to.assert_not_called()


# ---------------------------------------------------------------------------
# documents -> signature (opens the ceremony)
# ---------------------------------------------------------------------------
class TestFromDocuments:
    def _prime_documents_ok(self, h, monkeypatch, proc, *, files_present=True):
        renta = MagicMock(file_type="declaracion_renta")
        monkeypatch.setattr(
            h,
            "Files",
            MagicMock(
                list_by_process=MagicMock(
                    return_value=[renta] if files_present else []
                )
            ),
        )
        # MagicMock(name=...) sets the mock's display name, not an
        # attribute; assign explicitly.
        bank = MagicMock()
        bank.name = "Banco Popular"
        monkeypatch.setattr(
            h, "Banks", MagicMock(get_by_id=MagicMock(return_value=bank))
        )

    def test_missing_renta_doc_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "documents")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
        self._prime_documents_ok(h, monkeypatch, proc, files_present=False)

        # Ceremony opener must NOT be called when the gate fails.
        opener = MagicMock()
        monkeypatch.setattr(h, "open_ceremony_for_process", opener)

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "declaracion_renta_required"}
        opener.assert_not_called()
        proc.advance_to.assert_not_called()

    def test_happy_path_opens_ceremony_and_returns_sign_url(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "documents")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
        self._prime_documents_ok(h, monkeypatch, proc)

        opener = MagicMock(return_value="https://front.test/sign/sign_abc")
        monkeypatch.setattr(h, "open_ceremony_for_process", opener)

        resp = h.handler(_authed_event(str(uuid4())), None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["sign_url"] == "https://front.test/sign/sign_abc"
        assert body["process"]["stage"] == "documents"  # public_dict was captured pre-advance
        opener.assert_called_once()
        _, kw = opener.call_args
        assert kw["proc"] is proc
        assert kw["user"] is user
        assert kw["bank"].name == "Banco Popular"
        proc.advance_to.assert_called_once_with("signature")

    def test_signature_bridge_failure_returns_502(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "documents")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
        self._prime_documents_ok(h, monkeypatch, proc)

        bridge_error = h.SignatureBridgeError("signatures_invoke_failed", "boto boom")
        monkeypatch.setattr(
            h, "open_ceremony_for_process", MagicMock(side_effect=bridge_error)
        )

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 502
        assert (
            json.loads(resp["body"])["error"]
            == "signature_bridge_signatures_invoke_failed"
        )
        proc.advance_to.assert_not_called()


# ---------------------------------------------------------------------------
# signature -> payment (post-ceremony gate)
# ---------------------------------------------------------------------------
class TestFromSignature:
    def test_missing_sign_id_returns_400(self, load_handler, monkeypatch):
        """A row without sign_id means the ceremony was never opened
        (process created before Fase 6a, or previous transition failed
        halfway). Force the user to restart rather than skipping the
        signature step."""
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "signature", sign_id=None)
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
        monkeypatch.setattr(
            h, "Signatures", MagicMock(get_by_sign_id=MagicMock(return_value=None))
        )

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "signature_required"}

    def test_ceremony_not_signed_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "signature", sign_id="sign_xyz")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))

        ceremony = MagicMock(stage="otp")  # still in the middle of the ceremony
        monkeypatch.setattr(
            h,
            "Signatures",
            MagicMock(get_by_sign_id=MagicMock(return_value=ceremony)),
        )

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "signature_required"}
        proc.advance_to.assert_not_called()

    def test_signed_ceremony_advances_to_payment(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "signature", sign_id="sign_xyz")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))

        ceremony = MagicMock(stage="signed")
        monkeypatch.setattr(
            h,
            "Signatures",
            MagicMock(get_by_sign_id=MagicMock(return_value=ceremony)),
        )

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 200
        proc.advance_to.assert_called_once_with("payment")

    def test_lookup_uses_proc_sign_id(self, load_handler, monkeypatch):
        """Regression: the old v1 code did `get_active_for_process`
        which no longer exists. The new lookup must be by sign_id."""
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "signature", sign_id="sign_xyz")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))

        get_by_sign_id = MagicMock(return_value=MagicMock(stage="signed"))
        monkeypatch.setattr(h, "Signatures", MagicMock(get_by_sign_id=get_by_sign_id))

        h.handler(_authed_event(str(uuid4())), None)
        get_by_sign_id.assert_called_once_with("sign_xyz")


# ---------------------------------------------------------------------------
# terminal / cross-cutting
# ---------------------------------------------------------------------------
class TestTerminalAndOwnership:
    def test_done_is_idempotent(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        user = _patch_auth(monkeypatch)

        proc = _proc(user.id, "done")
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["process"]["stage"] == "done"
        assert "sign_url" not in body
        proc.advance_to.assert_not_called()

    def test_other_user_gets_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _patch_auth(monkeypatch, user_id="u-1")

        proc = _proc("u-2", "form")  # different owner
        monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))

        resp = h.handler(_authed_event(str(uuid4())), None)
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"]) == {"error": "process_not_found"}

    def test_invalid_uuid_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _patch_auth(monkeypatch)
        resp = h.handler(_authed_event("not-a-uuid"), None)
        assert resp["statusCode"] == 400
