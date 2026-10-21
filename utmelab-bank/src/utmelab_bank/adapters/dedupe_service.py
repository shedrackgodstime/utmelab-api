"""The dedupe service. Is this content new?

The gate asks whether a row is well formed. Dedupe asks whether it is new.
They are separate steps because they answer different questions, and the
state machine has a state for each.

A duplicate is counted, never silently overwritten. The item is refused with
the reason and the id of the row it duplicates, so a person can see whether
the duplicate is worth keeping.
"""

from __future__ import annotations

from typing import Optional

from utmelab_bank.domain.dedupe import Duplicate, near_duplicate_fingerprint
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.domain.ports import ContentIndex


class DedupeService:
    """Runs the dedupe step over a staging item.

    The index is the bank's own, and it holds what production holds as well
    as what the bank has produced, so a duplicate of either is caught.
    """

    def __init__(self, index: ContentIndex) -> None:
        self._index = index

    def fingerprint(self, item: StagingItem) -> str:
        """The near-duplicate fingerprint of an item's content."""
        return near_duplicate_fingerprint(
            item.content.stem.text,
            tuple(option.text.text for option in item.content.options),
        )

    async def find(self, item: StagingItem) -> Optional[Duplicate]:
        """The duplicate of this item, if there is one.

        The exact match wins, because a row that is the same content is a
        stronger finding than one that is a reworded copy.
        """
        content_hash = item.hashes.content_hash if item.hashes else ""
        if not content_hash:
            return None
        found = await self._index.find(
            content_hash=content_hash,
            near_duplicate=self.fingerprint(item),
        )
        return found

    async def apply(self, item: StagingItem) -> StagingItem:
        """Judge one item and move it on or refuse it."""
        found = await self.find(item)
        if found is not None:
            return item.transition_to(
                State.REJECTED,
                error=f"duplicate_{found.kind}: {found.question_id}",
            )
        return item.transition_to(State.DEDUPED)

    async def remember(self, item: StagingItem, *, origin: str) -> None:
        """Record an item in the index, so the next one finds it."""
        if item.hashes is None:
            return
        await self._index.remember(
            content_hash=item.hashes.content_hash,
            near_duplicate=self.fingerprint(item),
            origin=origin,
            question_id=item.id,
        )


__all__ = ["DedupeService"]
