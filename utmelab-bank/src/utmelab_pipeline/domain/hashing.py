"""Deterministic hashing.

The content hash is the contract with the production predicate. It must cover
the question, the options, the answer, the marks, the explanation, the passage
and the media evidence, so that any edit to any of them changes the hash and
invalidates a verification that was written against the old content.
"""

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
    """Hash of the raw source payload, used to detect upstream drift."""
    return sha256_hex(canonical_json_bytes(dict(payload)))


def _mark_key(mark: Any) -> str:
    return f"{mark.kind}:{mark.start}:{mark.length}:{mark.asset_id or ''}"


def _rich_text_key(text: Any) -> str:
    marks = "|".join(_mark_key(mark) for mark in text.marks)
    return f"{text.text}\x1f{marks}"


def content_fingerprint(
    *,
    stem: Any,
    options: Any,
    answer: str,
    marks: float,
    explanation: Any = None,
    passage: Any = None,
    media_assets: Any = (),
    catalog_version: str = "",
) -> str:
    """The fingerprint of the content a verification covers.

    Mirrors the production predicate: stem, options, answer, marks, the
    explanation, the passage and the media content hashes. Two runs over the
    same facts produce the same fingerprint, and any edit produces a different
    one.
    """
    parts: list[str] = [stem.text, "\x1e"]
    for option in options:
        parts.append(f"{option.id}\x1e{_rich_text_key(option.text)}\x1e")
    parts.append(f"{answer}\x1e{marks}\x1e")
    parts.append(_rich_text_key(explanation) if explanation is not None else "")
    parts.append("\x1e")
    parts.append(_rich_text_key(passage.text) if passage is not None else "")
    parts.append("\x1e")
    for asset in media_assets:
        parts.append(f"{asset.asset_id}\x1e")
    parts.append(catalog_version)
    return sha256_hex("\x1f".join(parts).encode("utf-8"))
