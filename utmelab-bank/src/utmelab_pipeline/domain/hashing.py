"""Deterministic hashing for source payloads and canonical content."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_hash(payload: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(dict(payload)))
