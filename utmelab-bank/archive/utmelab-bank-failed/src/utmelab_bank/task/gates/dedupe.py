"""Duplicate detection, and the task that refuses.

The fingerprint is stem plus sorted options, ported from ``quarantine.rs`` and
``import.rs``. Sorting the options is what makes it answer "is this the same
question" rather than "is this byte identical": a re-scraped paper whose options
were reordered still collides with the version already held.

The version that shipped as `drop_rows.py` / `dup_audit.py` in the archive wrote
a fingerprint column and then refused nothing — ``count(id == my own id)`` is
always one, so nothing could ever collide with itself. This replaces it with two
indexed lookups:

- **exact**: same stem and same options as an existing row. Never allowed.
- **same stem, same answer letter**: the dangerous middle — two rows that agree
  on which letter is right while disagreeing on what the letters are.
- **same stem, different options:** left for a person; logged but not refused,
  because two years' papers ask "which of these is not a source document?" with
  different option sets and different correct answers, and both are real
  questions.

To keep both buckets indexed the row carries ``stem_key``: the normalised stem
alone. One query matches the fingerprint (exact) and one matches the stem key
(same stem). Counting everything in python was how the old audit became
quadratic on every hand of 200 questions; indexing it is what makes the check
cheap enough to run on every batch.
"""

from __future__ import annotations

import logging
from typing import Any

from utmelab_bank.rules import option_texts_of
from utmelab_bank.store.fingerprint import normalise_for_compare, stem_fingerprint
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["Dedupe", "classify", "fingerprint_row"]

log = logging.getLogger(__name__)


def fingerprint_row(row: dict[str, Any]) -> str:
    """One row's content fingerprint."""
    return stem_fingerprint(str(row.get("text") or ""), option_texts_of(row))


def classify(
    existing_stem: str,
    existing_options: list[str],
    existing_answer: str,
    incoming_stem: str,
    incoming_options: list[str],
    incoming_answer: str,
) -> str:
    """Which kind of near-duplicate this is, if any.

    From ``tools/dup_audit.py``: same stem and same options is exact; same stem
    and same key letter is the dangerous middle; same stem and different options
    is the legitimate case.

    The key is the answer letter the row carries, compared case-insensitively.
    An empty key on either side is not a shared key: two rows that both lost
    their answer are not thereby evidence of being the same question.
    """
    if normalise_for_compare(existing_stem) != normalise_for_compare(incoming_stem):
        return "distinct"
    existing_options_norm = sorted(normalise_for_compare(o) for o in existing_options)
    incoming_options_norm = sorted(normalise_for_compare(o) for o in incoming_options)
    if existing_options_norm == incoming_options_norm:
        return "exact"
    existing_key = existing_answer.strip().upper()
    incoming_key = incoming_answer.strip().upper()
    if existing_key and existing_key == incoming_key:
        return "same_stem_same_key"
    return "shared_stem"


@registered
class Dedupe:
    """Fingerprint each row and refuse a genuine repeat."""

    name = "dedupe"
    produces = "fingerprint"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    needs_reference = True
    description = "Refuse a second row with the same stem and the same options."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> Any:
        return await fingerprint_and_refuse(row, ctx)

    async def collect(self, _ctx: TaskContext) -> list[Any]:
        return []


async def fingerprint_and_refuse(row: dict[str, Any], ctx: TaskContext) -> Any:
    """Stamp the fingerprint, then refuse a genuine repeat.

    One row's duplicate is by definition *another* row, so this checks the lane
    excluding itself. The old version counted the row's own id and passed every
    time; this checks only rows that were already written.
    """
    row_id = str(row.get("id", ""))
    if not row_id:
        return ctx.skip(row_id, "no_id", "the row has no id")

    digest = fingerprint_row(row)
    stem_key = normalise_for_compare(str(row.get("text") or ""))
    log.debug("dedupe %s: digest=%s stem_key=%s", row_id, digest, stem_key)

    content_hash = str(row.get("content_hash") or "")
    if ctx.reference is not None and await ctx.reference.has_content_hash(content_hash):
        return ctx.skip(
            row_id,
            "duplicate_production",
            f"{content_hash[:12]} is already served",
        )

    if ctx.dry_run:
        return ctx.ok(row_id)

    await ctx.repo.update("questions", row_id, {"fingerprint": digest, "stem_key": stem_key})

    collisions = await _collisions(ctx, row, row_id, digest, stem_key)
    log.debug("dedupe %s: collisions=%s", row_id, collisions)
    if collisions["exact"]:
        return ctx.skip(
            row_id,
            "duplicate_fingerprint",
            f"identical to {collisions['exact'][0]}",
        )
    if collisions["same_stem_same_key"]:
        return ctx.skip(
            row_id,
            "duplicate_fingerprint",
            f"same stem and answer as {collisions['same_stem_same_key'][0]}, different options",
        )
    if collisions["shared_stem"]:
        log.info(
            "%s shares a stem with %d row(s) and different options; leaving for a person",
            row_id,
            len(collisions["shared_stem"]),
        )
    return ctx.ok(row_id)


async def _collisions(
    ctx: TaskContext,
    row: dict[str, Any],
    row_id: str,
    digest: str,
    stem_key: str,
) -> dict[str, list[str]]:
    """Which earlier rows this row collides with, by bucket.

    One indexed lookup instead of scanning the lane: the candidates are the rows
    sharing this row's fingerprint (the exact bucket) or its stem key (the other
    two). Reading through ``collision_candidates`` rather than a ``--where``
    selector is deliberate, because a stem key is data and can contain the word
    "and", which the selector grammar splits on.
    """
    found: dict[str, list[str]] = {"exact": [], "same_stem_same_key": [], "shared_stem": []}
    incoming_answer = str(row.get("answer") or "")

    candidates = await ctx.repo.collision_candidates(
        "questions",
        fingerprint=digest,
        stem_key=stem_key,
        exclude_id=row_id,
    )
    for other in candidates:
        other_id = str(other.get("id", ""))
        if not other_id:
            continue
        bucket = classify(
            str(other.get("text") or ""),
            option_texts_of(other),
            str(other.get("answer") or ""),
            str(row.get("text") or ""),
            option_texts_of(row),
            incoming_answer,
        )
        if bucket != "distinct" and other_id not in found[bucket]:
            found[bucket].append(other_id)
    return found
