"""Shared text handling. No IO, no configuration, no models beyond RichText.

Every helper here exists because it was duplicated. If a task needs a text
routine and cannot find it here, the routine belongs here rather than in the
task.
"""

from __future__ import annotations

from utmelab_bank.text.htmltext import (
    CLOZE_HINT,
    INLINE_TAGS,
    NUMBERED_GAP,
    PROMISED_STIMULUS,
    clean_inline,
    has_numbered_gap,
    mentions_cloze,
    mentions_figure,
    promises_stimulus,
    strip_tags,
    unescape_once,
    visible_lines,
)
from utmelab_bank.text.richtext import (
    clean_blocks,
    from_json,
    join_rich,
    merge_words,
    offset_of,
    rt,
    rt_json,
    snap,
    unescape_segment,
)
from utmelab_bank.text.slug import slugify

__all__ = [
    "CLOZE_HINT",
    "INLINE_TAGS",
    "NUMBERED_GAP",
    "PROMISED_STIMULUS",
    "has_numbered_gap",
    "mentions_cloze",
    "clean_inline",
    "from_json",
    "mentions_figure",
    "clean_blocks",
    "join_rich",
    "merge_words",
    "offset_of",
    "promises_stimulus",
    "rt",
    "rt_json",
    "slugify",
    "snap",
    "strip_tags",
    "unescape_segment",
    "unescape_once",
    "visible_lines",
]
