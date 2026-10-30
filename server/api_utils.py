"""Transport-neutral JSON response encoding and validation."""

from __future__ import annotations
import json


def encode_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_length(header: str, limit: int) -> int:
    try:
        count = int(header)
    except (ValueError, TypeError):
        raise ValueError("Invalid Content-Length")
    if count < 0 or count > limit:
        raise ValueError("Request exceeds size limit")
    return count
