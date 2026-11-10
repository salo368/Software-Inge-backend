"""S3 ObjectCreated trigger for the files bucket.

The worker fetches the object's HEAD metadata and registers a row in
`files`. `process_id` and `file_type` come from the object metadata
(`x-amz-meta-process-id` / `x-amz-meta-file-type`), never from the key.
`s3_key` is UNIQUE at the DB level, so a duplicate delivery of the same
event (S3 only guarantees at-least-once) fails the insert instead of
creating a second row; the per-record try/except in `handler` just logs it.
"""
from urllib.parse import unquote, unquote_plus
from uuid import UUID

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.core.s3 import head_object
from libs.orm.files import Files, FileType

VALID_TYPES = {member.value for member in FileType}


def handler(event, context):
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as e:
            Logger.log("ERROR", f"on_upload failed for {record}: {e}")
    db_session.commit()
    return {"processed": len(event.get("Records", []))}


def _process_record(record: dict) -> None:
    s3 = record["s3"]
    bucket = s3["bucket"]["name"]
    key = unquote_plus(s3["object"]["key"])

    head = head_object(bucket, key)
    metadata = head.get("Metadata") or {}

    try:
        process_id = UUID(metadata.get("process-id"))
    except (TypeError, ValueError):
        Logger.log("WARNING", f"ignoring {key}: missing or invalid process-id metadata")
        return

    file_type = metadata.get("file-type")
    if file_type not in VALID_TYPES:
        Logger.log("WARNING", f"ignoring {key}: missing or invalid file-type metadata")
        return

    # The user-facing name is stored percent-encoded, since S3 metadata
    # must be ASCII.
    stored_name = metadata.get("original-name")
    original_name = unquote(stored_name) if stored_name else None

    Files.create(
        process_id=process_id,
        file_type=file_type,
        s3_key=key,
        original_name=original_name,
        size_bytes=head.get("ContentLength"),
        content_type=head.get("ContentType"),
    )

    Logger.log("INFO", f"registered file {key} for process {process_id}")
