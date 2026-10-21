"""Deterministic hashing.

Two hashes matter.

- ``payload_hash`` covers the raw source payload. It detects upstream drift.
- ``content_fingerprint`` is the production contract. It is the value stored in
  ``questions.content_hash`` and in ``verifications.content_hash``, and the
  serving predicate compares those two stored columns.

The fingerprint mirrors ``Question::content_fingerprint`` in
``utmelab-api-old/src/bank/model.rs`` exactly. If this file and that function
ever disagree, no row we write can match a production row, so the two are
changed together.

What the fingerprint does **not** cover: the passage text, the media, the
section and the difficulty. That is finding F18 in ``FINDINGS.md`` and it is
still true of production.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

#: Separates the parts of a fingerprint.
PART = "\x1f"

#: Separates an option id from its text.
FIELD = "\x1e"


def canonical_json_bytes(value: object) -> bytes:
    """The one way we turn a value into bytes for hashing or storing."""
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


def mark_key(mark: Any) -> str:
    """Encode one mark the way production encodes it.

    ``<start>,<len>,<kind>``. An image mark carries its url, its position and
    its alt text, in that order, with an empty alt when there is none.
    """
    kind = mark.kind
    if getattr(kind, "value", kind) == "image":
        position = mark.position
        position_value = getattr(position, "value", position) or ""
        alt = mark.alt or ""
        return f"{mark.start},{mark.len},image:{mark.url}:{position_value}:{alt}"
    return f"{mark.start},{mark.len},{getattr(kind, 'value', kind)}"


def _marks_key(marks: Any) -> str:
    return "|".join(mark_key(mark) for mark in marks)


def fingerprint_parts(parts: list[str]) -> str:
    """Join the parts and hash them. This is production's ``fingerprint_parts``."""
    return sha256_hex(PART.join(parts).encode("utf-8"))


def content_fingerprint(
    *,
    stem: Any,
    options: Any,
    answer: str,
    explanation: Any = None,
) -> str:
    """The fingerprint of the content a verification covers.

    The parts, in order, exactly as production builds them:

    1. the stem text
    2. for each option, the option id and its text
    3. the answer
    4. the marks of the stem, then the marks of each option
    5. the explanation key point text, then its marks
    6. the explanation body text, then its marks
    7. the trap text, then its marks, or an empty string when there is none
    """
    parts: list[str] = [stem.text]
    for option in options:
        parts.append(f"{option.id}{FIELD}{option.text.text}")
    parts.append(answer)

    marks = [mark_key(mark) for mark in stem.marks]
    for option in options:
        marks.extend(mark_key(mark) for mark in option.text.marks)
    parts.append("|".join(marks))

    if explanation is None:
        parts.append("")
    else:
        parts.append(explanation.key_point.text)
        parts.append(_marks_key(explanation.key_point.marks))
        parts.append(explanation.body.text)
        parts.append(_marks_key(explanation.body.marks))
        if explanation.trap is None:
            parts.append("")
        else:
            parts.append(explanation.trap.text)
            parts.append(_marks_key(explanation.trap.marks))

    return fingerprint_parts(parts)


def text_norm(stem_text: str) -> str:
    """The lowercased stem, the way production stores it in ``text_norm``."""
    return stem_text.lower()
