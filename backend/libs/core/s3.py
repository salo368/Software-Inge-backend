"""Cross-service S3 helpers: raw byte uploads and presigned URLs.

Callers must have IAM for s3:PutObject / s3:GetObject on the target bucket.
For presigned PUT URLs the browser will PUT directly with the given
`Content-Type` header, so pass a stable value.
"""
from __future__ import annotations

import boto3
from botocore.client import Config

_client = boto3.client("s3", config=Config(signature_version="s3v4"))

DEFAULT_UPLOAD_TTL = 900   # 15 min
DEFAULT_DOWNLOAD_TTL = 900


def upload_from_bytes(bucket: str, key: str, data: bytes, content_type: str | None = None) -> None:
    kwargs = {"Bucket": bucket, "Key": key, "Body": data}
    if content_type:
        kwargs["ContentType"] = content_type
    _client.put_object(**kwargs)


def presign_upload(bucket: str, key: str, content_type: str,
                   expires: int = DEFAULT_UPLOAD_TTL) -> str:
    return _client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
        HttpMethod="PUT",
    )


def presign_download(bucket: str, key: str, expires: int = DEFAULT_DOWNLOAD_TTL,
                     filename: str | None = None) -> str:
    params: dict = {"Bucket": bucket, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return _client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=expires,
        HttpMethod="GET",
    )


def head_object(bucket: str, key: str) -> dict:
    return _client.head_object(Bucket=bucket, Key=key)
