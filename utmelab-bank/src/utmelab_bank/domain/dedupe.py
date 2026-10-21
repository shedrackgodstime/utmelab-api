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


def near_duplicate_fingerprint(stem: str, option_texts: tuple[str, ...]) -> str:
    """The fingerprint that catches the same question seen twice.

    The lowercased stem, then the sorted lowercased option texts, joined.
    Sixteen hex characters, which is enough to be a key and short enough to
    be an index entry.

    It catches a different case, the options in a different order, and
    padding. It does not catch a rewritten stem or a reworded option, and
    it is not meant to.
    """
    options = sorted(text.strip().lower() for text in option_texts)
    joined = stem.strip().lower() + GAP + "~".join(options)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


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


__all__ = ["GAP", "Duplicate", "near_duplicate_fingerprint"]
