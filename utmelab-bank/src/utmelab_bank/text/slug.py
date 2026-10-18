"""``slugify``, once.

Three copies existed: in the JAMB syllabus importer, the WAEC syllabus importer
and the WAEC inbox merger, each a few characters apart. A slug is a primary key
in every catalog table, so a divergence here is a silent fork rather than a
crash.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["SLUG_MAX", "slugify"]

#: Long enough for any subject or topic name we have seen, short enough that a
#: slug still fits a url path without truncation.
SLUG_MAX: int = 120

_SEPARATORS: re.Pattern[str] = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_length: int = SLUG_MAX) -> str:
    """A url-safe key from a display name.

    Accents are folded rather than dropped, so ``Poincaré`` becomes ``poincare``
    and not ``poincar``. The old normalisers stripped everything outside
    ``[a-z0-9]``, which silently turned ``Économie`` into ``conomie``.
    """
    folded = unicodedata.normalize("NFKD", text)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    slug = _SEPARATORS.sub("-", ascii_only.casefold()).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug
