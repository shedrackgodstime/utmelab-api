"""Dedupe. Two fingerprints, because there are two kinds of duplicate.

The **exact hash** catches a row copied verbatim. It never collides, so a
duplicate check on it is a lookup, and it is the receipt every review is
written against.

The **near-duplicate fingerprint** catches the same question presented
differently. It is the live rule from ``tools/review.py``: the lowercased
stem plus the sorted lowercased option texts, joined, and hashed to sixteen
hex characters.

What it catches, measured against the live rule: different capitalisation,
the options in a different order, and padding. What it does not catch: a
stem that was rewritten, or an option that was reworded, because the stem
and the options are both part of the key.

So it is not a similarity measure and it does not pretend to be. It is the
fingerprint for the same question seen twice, and the same question seen
twice with the options shuffled is the duplicate that actually happens.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: Separates the stem from the options in the near-duplicate fingerprint.
#: It cannot occur in a question, so it cannot be forged by one.
GAP = "|"

#: Separates the year from the fingerprint it qualifies.
YEAR_GAP = "\x1f"


def near_duplicate_fingerprint(
    stem: str,
    option_texts: tuple[str, ...],
    image_keys: tuple[str, ...] = (),
) -> str:
    """The fingerprint that catches the same question seen twice.

    The lowercased stem, then the sorted lowercased option texts, then the
    images the question carries. Sixteen hex characters, which is enough to
    be a key and short enough to be an index entry.

    The image is part of the key because a question and its options can be
    identical while the diagram is not. Two rows that differ only in their
    figure are different questions, and the bank should not refuse the second
    one as a copy of the first. An empty image list keeps the old shape for
    the callers that have no media, which is most of the gate's callers.
    """
    options = sorted(text.strip().lower() for text in option_texts)
    joined = stem.strip().lower() + GAP + "~".join(options)
    if image_keys:
        joined += GAP + "~".join(sorted(str(key) for key in image_keys))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def duplicate_content_key(content_hash: str, year: int) -> str:
    """The exact-duplicate key for one content hash in one exam year.

    Production's ``content_hash`` is a hash of the question alone. Its
    contract must stay that way, because the serving predicate compares it
    with a verification. The bank, however, wants the same question in 2025
    and 2026 to be two rows, so the index key adds the year. Two rows with
    the same content and the same year collide; the same content in a
    different year does not.
    """
    return hashlib.sha256(f"{content_hash}{YEAR_GAP}{year}".encode()).hexdigest()


def duplicate_near_key(near_duplicate: str, year: int) -> str:
    """The near-duplicate key for one fingerprint in one exam year."""
    return hashlib.sha256(f"{near_duplicate}{YEAR_GAP}{year}".encode()).hexdigest()


@dataclass(frozen=True)
class Duplicate:
    """One row that is already held, and how it was found.

    ``exact`` means the content hash matched, so the content is the same.
    ``near`` means the fingerprint matched, so the content is a reworded
    copy. Both are counted, and neither is ever silently overwritten.
    """

    kind: str
    question_id: str

    def __post_init__(self) -> None:
        if self.kind not in ("exact", "near"):
            raise ValueError(f"unknown duplicate kind {self.kind!r}")


__all__ = [
    "GAP",
    "YEAR_GAP",
    "Duplicate",
    "duplicate_content_key",
    "duplicate_near_key",
    "near_duplicate_fingerprint",
]
