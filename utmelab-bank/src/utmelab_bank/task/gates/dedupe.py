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
import sys
from typing import Any

from utmelab_bank.errors import StoreError
from utmelab_bank.rules import load_json_column
from utmelab_bank.store.fingerprint import normalise_for_compare, stem_fingerprint
from utmelab_bank.store.selectors import Selector, SelectorSet, all_names, register, resolve
from utmelab_bank.task.base import Task, TaskContext, registered

__all__ = ["Dedupe", "fingerprint_row", "classify"]

log = logging.getLogger(__name__)


def fingerprint_row(row: dict[str, Any]) -> str:
    """One row's content fingerprint."""
    return stem_fingerprint(str(row.get("text") or ""), option_texts_of(row))


def option_texts_of(row: dict[str, Any]) -> list[str]:
    entries = load_json_column(row, "options", [])
    texts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        texts.append(str(body.get("text", "")) if isinstance(body, dict) else str(body))
    return texts


def classify(
    existing_stem: str,
    existing_options: list[str],
    incoming_stem: str,
    incoming_options: list[str],
) -> str:
    """Which kind of near-duplicate this is, if any.

    From ``tools/dup_audit.py``: same stem and same options is exact; same stem
    and same key letter is the dangerous middle; same stem and different options
    is the legitimate case.

    Option letters come off as uppercase, so comparison is case-insensitive.
    """
    from utmelab_bank.store.fingerprint import normalise_for_compare

    if normalise_for_compare(existing_stem) != normalise_for_compare(incoming_stem):
        return "distinct"
    existing_options_norm = sorted(normalise_for_compare(o) for o in existing_options)
    incoming_options_norm = sorted(normalise_for_compare(o) for o in incoming_options)
    if existing_options_norm == incoming_options_norm:
        return "exact"
    return "shared_stem"


@registered
class Dedupe:
    """Fingerprint each row and refuse a genuine repeat."""

    name = "dedupe"
    produces = "fingerprint"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Refuse a second row with the same stem and the same options."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> Any:
        return await fingerprint_and_refuse(row, ctx)

    async def collect(self, ctx: TaskContext) -> list[Any]:
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
    print(f"DEBUG: row_id={row_id}, digest={digest}, stem_key={stem_key}", file=sys.stderr)
    if ctx.dry_run:
        return ctx.ok(row_id)

    print(f"DEBUG: about to update row {row_id} with fingerprint={digest}, stem_key={stem_key}", file=sys.stderr)
    await ctx.repo.update("questions", row_id, {"fingerprint": digest, "stem_key": stem_key})
    print(f"DEBUG: update done", file=sys.stderr)

    collisions = await _collisions(ctx, row_id, digest, stem_key)
    print(f"DEBUG: collisions={collisions}", file=sys.stderr)
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
            f"same stem and answer as {collisions['same_stem_same_key'][0]}, "
            "different options",
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
    row_id: str,
    digest: str,
    stem_key: str,
) -> dict[str, list[str]]:
    """Which earlier rows this row collides with, by bucket.

    Two indexed lookups instead of scanning the lane: one for the full
    fingerprint and one for rows sharing the stem key. Querying the lane is what
    lets this run at batch size instead of scanning every row the lane holds.
    """
    found: dict[str, list[str]] = {"exact": [], "same_stem_same_key": [], "shared_stem": []}

    print(f"DEBUG: querying exact fingerprint={digest}", file=sys.stderr)
    print(f"DEBUG _collisions: querying fingerprint={digest}", file=sys.stderr)
    print(f"DEBUG _collisions: querying fingerprint={digest}", file=sys.stderr)
    exact = await ctx.repo.rows("questions", f"fingerprint={digest}")
    print(f"DEBUG _collisions: exact rows = {[(r.get('id'), r.get('fingerprint')) for r in exact]}", file=sys.stderr)
    print(f"DEBUG: exact rows: {[(r.get('id'), r.get('fingerprint')) for r in exact]}", file=sys.stderr)
    print(f"DEBUG: exact results: {[(r.get('id'), r.get('fingerprint')) for r in exact]}", file=sys.stderr)
    for other in exact:
        other_id = str(other.get("id", ""))
        if other_id and other_id != row_id:
            found["exact"].append(other_id)

    print(f"DEBUG: querying stem_key={stem_key}", file=sys.stderr)
    stems = await ctx.repo.rows("questions", f"stem_key={stem_key}")
    print(f"DEBUG: stem results: {[(r.get('id'), r.get('stem_key')) for r in stems]}", file=sys.stderr)
    for other in stems:
        other_id = str(other.get("id", ""))
        if not other_id or other_id == row_id:
            continue
        options = option_texts_of(other)
        bucket = classify(
            str(other.get("text") or ""),
            options,
            str(row.get("text") or ""),
            option_texts_of(row),
        )
        if bucket == "exact" and other_id not in found["exact"]:
            found["exact"].append(other_id)
        elif bucket == "same_stem_same_key":
            found["same_stem_same_key"].append(other_id)
        elif bucket == "shared_stem":
            found["shared_stem"].append(other_id)
    return found


def option_texts_of(row: dict[str, Any]) -> list[str]:
    entries = load_json_column(row, "options", [])
    texts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        texts.append(str(body.get("text", "")) if isinstance(body, dict) else str(body))
    return texts
