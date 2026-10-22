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
from collections.abc import Mapping, Sequence
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


def mark_key(inline: Any) -> str:
    """Encode one inline the way production encodes it.

    The name is production's own, so the two can be compared line for line:
    the Rust is ``fn mark_key(m: &Inline) -> String``. Production calls an
    inline a mark in this one place and an inline everywhere else.

    ``<start>,<len>,<kind>``. An image inline carries its value, its position
    and its alt text, in that order, with an empty alt when there is none. The
    value is the source url before capture and the stored name after, so the
    fingerprint follows the record rather than a host.
    """
    kind = inline.kind
    if getattr(kind, "value", kind) == "image":
        position = inline.position
        position_value = getattr(position, "value", position) or ""
        alt = inline.alt or ""
        return f"{inline.start},{inline.len},image:{inline.url}:{position_value}:{alt}"
    return f"{inline.start},{inline.len},{getattr(kind, 'value', kind)}"


def _inline_key(inline: Any) -> str:
    return "|".join(mark_key(one) for one in inline)


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
    4. the inline of the stem, then the inline of each option
    5. the explanation key point text, then its inline
    6. the explanation body text, then its inline
    7. the trap text, then its inline, or an empty string when there is none
    """
    parts: list[str] = [stem.text]
    for option in options:
        parts.append(f"{option.id}{FIELD}{option.text.text}")
    parts.append(answer)

    inline = [mark_key(mark) for mark in stem.inline]
    for option in options:
        inline.extend(mark_key(mark) for mark in option.text.inline)
    parts.append("|".join(inline))

    if explanation is None:
        parts.append("")
    else:
        parts.append(explanation.key_point.text)
        parts.append(_inline_key(explanation.key_point.inline))
        parts.append(explanation.body.text)
        parts.append(_inline_key(explanation.body.inline))
        if explanation.trap is None:
            parts.append("")
        else:
            parts.append(explanation.trap.text)
            parts.append(_inline_key(explanation.trap.inline))

    return fingerprint_parts(parts)


def bundle_fingerprint(
    *,
    content_hash: str,
    passage_id: str | None = None,
    passage_text: str = "",
    passage_inline: Sequence[Any] = (),
    section: str | None = None,
    media_ids: Sequence[str] = (),
) -> str:
    """The bank's own fingerprint of the row as a bundle.

    Production's ``content_hash`` covers the stem, the options, the answer,
    the inline and the explanation, and nothing else. A row can still change
    in the parts it does not cover: the passage it needs, the section it sits
    in, and the media it carries. This fingerprint covers those too, so the
    bank can tell when the bundle a reviewer signed is no longer the bundle
    on the row. It is the bank's value; production never sees it.
    """
    parts: list[str] = [content_hash]
    parts.append(passage_id or "")
    parts.append(passage_text)
    parts.append(_inline_key(passage_inline))
    parts.append(section or "")
    parts.extend(f"media:{asset_id}" for asset_id in media_ids)
    return fingerprint_parts(parts)


def text_norm(stem_text: str) -> str:
    """The lowercased stem, the way production stores it in ``text_norm``."""
    return stem_text.lower()
