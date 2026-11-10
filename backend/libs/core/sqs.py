"""Thin SQS wrapper. Callers must have IAM for sqs:SendMessage on the
target queue."""
from __future__ import annotations

import boto3

_client = boto3.client("sqs")


def send_message(queue_url: str, body: str, delay_seconds: int = 0) -> None:
    _client.send_message(QueueUrl=queue_url, MessageBody=body, DelaySeconds=delay_seconds)
