"""Passages are bank content, read from the bank lane.

A passage is extracted from the same source page as its question and carried
through the raw, work and ready lanes. It is not production reference data: a
question that exists only in the bank has a passage that exists only in the
bank. Reading production here would miss every one of those rows and, worse,
could attach a different year's stimulus to a question that was never served.

Callers treat ``None`` as a gap: a row that points at a passage the lane does
not hold cannot be explained or checked honestly.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.store.repository import Repository

__all__ = ["passage_by_id", "passage_for", "passage_text"]


async def passage_by_id(repo: Repository, passage_id: str) -> dict[str, Any] | None:
    """One passage from the bank lane, or ``None``."""
    if not passage_id:
        return None
    found = await repo.rows("passages", f"id={passage_id}")
    return dict(found[0]) if found else None


async def passage_for(repo: Repository, row: dict[str, Any]) -> dict[str, Any] | None:
    """The passage a row points at, from the row's own lane, or ``None``."""
    return await passage_by_id(repo, str(row.get("passage_id") or ""))


def passage_text(passage: dict[str, Any] | None) -> str:
    """The stimulus text, or the empty string when there is none."""
    if not passage:
        return ""
    return str(passage.get("text") or "")
