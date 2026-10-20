"""The internal stem fingerprint, which is not the content hash.

Two different hashes exist in this package and confusing them is the mistake
this docstring exists to prevent.

``contract.content_hash`` is the boundary hash. The API joins on it, it is
pinned by test vectors, and changing it re-hashes the whole bank.

This one is internal. It answers "have we seen this question before?", it is
computed during intake, and it may change freely because nothing outside this
package reads it.

The repository held five fingerprints with different widths and different
normalisations, and two of them were called ``fingerprint`` while meaning
different things. One name, one place, one purpose.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Sequence

from utmelab_bank.model.richtext import RichText

__all__ = ["normalise_for_compare", "stem_fingerprint"]

#: Marks are dropped before hashing, because an underline is presentation and two
#: rows differing only in presentation are the same question.
_TAGS: re.Pattern[str] = re.compile(r"<[^>]+>")

#: Whitespace collapses to one space so a line wrap does not make a new question.
_WS: re.Pattern[str] = re.compile(r"\s+")

#: Dropped rather than translated to "?", because the old normaliser did that
#: and silently deleted every Arabic and Hausa question in the bank.
_PUNCT: re.Pattern[str] = re.compile(r"[^\w\s]", re.UNICODE)


def normalise_for_compare(text: str) -> str:
    """Fold text down to what makes two questions the same question.

    Case, accents, punctuation, markup and whitespace go. Letters do not.

    That last part is not a preference. ``tools/dup_audit.py`` carries the note:

        The normaliser keeps every unicode letter and digit. An earlier version
        used ``[^a-z0-9]``, which deleted Arabic and Hausa text entirely and
        made 66 perfectly good rows look like one duplicate, a false alarm that
        a real duplication check must never raise.

    So the character class is ``\\w`` and not ``[a-z0-9]``, and a test below pins
    that an Arabic stem does not normalise to nothing.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = _TAGS.sub(" ", folded)
    folded = _PUNCT.sub("", folded)
    return _WS.sub(" ", folded.casefold()).strip()


def stem_fingerprint(
    stem: RichText | str,
    options: Sequence[str] | None = None,
) -> str:
    """A content fingerprint: stem plus sorted options, 16 hex characters.

    Ported from ``quarantine.rs`` and ``import.rs``, which compute the same
    thing: lowercase, trim, sort the options, join them with ``~``, append the
    stem, sha256, take the first eight bytes.

    **The options are folded in, and that is the whole point.** The earlier
    version of this function accepted an ``options`` argument and never read it,
    on the argument that two rows sharing a stem with different options is the
    interesting case. Every reference does the opposite: options are sorted and
    included precisely so that a re-scraped paper whose options were reordered
    still collides with the version already held.

    Sorting rather than keeping order is deliberate. It is what makes the
    fingerprint answer "is this the same question" rather than "is this byte
    identical".

    Sixteen characters rather than sixty four because this is an internal index
    key and a collision costs one row to re-check. The boundary hash is a
    different function with a different job.
    """
    text = stem.text if isinstance(stem, RichText) else stem
    body = normalise_for_compare(text)
    tail = []
    for option in options or []:
        cleaned = normalise_for_compare(str(option))
        if cleaned:
            tail.append(cleaned)
    tail.sort()
    joined = f"{body}|{'~'.join(tail)}"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
