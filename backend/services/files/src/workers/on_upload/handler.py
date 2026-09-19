"""S3 ObjectCreated trigger for the files bucket.

Keys look like: processes/{process_id}/{file_type}/{file_uuid}.{ext}
The worker parses the key, fetches HEAD metadata, and registers a row in
`files`. Idempotent: if the key already exists we skip.
"""
from urllib.parse import unquote, unquote_plus
from uuid import UUID

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.core.s3 import head_object
from libs.orm.files import Files


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

    parts = key.split("/")
    if len(parts) < 4 or parts[0] != "processes":
        Logger.log("WARNING", f"ignoring unexpected key {key}")
        return

    _, process_id_raw, file_type, filename = parts[0], parts[1], parts[2], "/".join(parts[3:])
    try:
        process_id = UUID(process_id_raw)
    except ValueError:
        Logger.log("WARNING", f"invalid process_id in key {key}")
        return

    if Files.get_by_key(key) is not None:
        Logger.log("INFO", f"file already registered: {key}")
        return

    head = head_object(bucket, key)
    # get_upload_url stores the user-facing name here percent-encoded, since
    # the key itself is a uuid. Fall back to the key's filename.
    stored_name = (head.get("Metadata") or {}).get("original-name")
    original_name = unquote(stored_name) if stored_name else filename

    Files.register_from_s3(
        process_id=process_id,
        file_type=file_type,
        s3_key=key,
        original_name=original_name,
        size_bytes=head.get("ContentLength"),
        content_type=head.get("ContentType"),
    )
    Logger.log("INFO", f"registered file {key} for process {process_id}")
