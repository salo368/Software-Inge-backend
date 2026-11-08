"""Where payment receipts live in the shared files bucket. The `payments/`
prefix is outside the `processes/` prefix that triggers files.on_upload, so
receipts are never registered in the `files` table."""
from __future__ import annotations


def payment_key_prefix(process_id) -> str:
    return f"payments/{process_id}/"


def build_payment_key(process_id, file_id, ext: str = "") -> str:
    return f"{payment_key_prefix(process_id)}{file_id}{ext}"
