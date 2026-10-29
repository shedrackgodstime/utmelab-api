"""The dedupe service. Is this content new?

The gate asks whether a row is well formed. Dedupe asks whether it is new.
They are separate steps because they answer different questions, and the
state machine has a state for each.

A duplicate is counted, never overwritten. The item is refused with the reason
and the id of the row it duplicates; the scrape counts that refusal but does
not store the copy, because the index already holds the original.

The two keys carry the exam year. The same question in 2025 and 2026 is two
rows, because a paper is a year's paper; the same question twice in one year
is a duplicate. The image is part of the near key, because two questions can
share a stem and options and still show different diagrams.
"""

from __future__ import annotations

from utmelab_bank.domain.dedupe import (
    Duplicate,
    duplicate_content_key,
    duplicate_near_key,
    near_duplicate_fingerprint,
)
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import Inline, RichText, StagingItem
from utmelab_bank.domain.ports import ContentIndex


def _image_keys(rich: RichText) -> tuple[str, ...]:
    """The image anchors in one rich text, in a stable form.

    The stored name is the image's identity in the bank, so the key uses the
    url field exactly as the record holds it. The position and alt travel
    with it because the same image above the stem is not the same document
    as the same image below it.
    """
    keys: list[str] = []
    for inline in rich.inline:
        if _is_image(inline):
            keys.append(f"{inline.url}|{_value(inline.position)}|{inline.alt or ''}")
    return tuple(keys)


def _is_image(inline: Inline) -> bool:
    return _value(inline.kind) == "image"


def _value(value: object) -> str:
    return str(getattr(value, "value", value) or "")


class DedupeService:
    """Runs the dedupe step over a staging item.

    The index is the bank's own, and it holds what production holds as well
    as what the bank has produced, so a duplicate of either is caught.
    """

    def __init__(self, index: ContentIndex) -> None:
        self._index = index

    def fingerprint(self, item: StagingItem) -> str:
        """The near-duplicate fingerprint of an item's content.

        Images are included. A question with a different figure is a
        different question even when its words are identical.
        """
        images: list[str] = []
        images.extend(_image_keys(item.content.stem))
        for option in item.content.options:
            images.extend(_image_keys(option.text))
        return near_duplicate_fingerprint(
            item.content.stem.text,
            tuple(option.text.text for option in item.content.options),
            tuple(images),
        )

    def content_key(self, item: StagingItem) -> str:
        """The exact-duplicate key for this item's content and year."""
        content_hash = item.hashes.content_hash if item.hashes else ""
        return duplicate_content_key(content_hash, item.provenance.scope.year)

    def near_key(self, item: StagingItem) -> str:
        """The near-duplicate key for this item's content and year."""
        return duplicate_near_key(self.fingerprint(item), item.provenance.scope.year)

    async def find(self, item: StagingItem) -> Duplicate | None:
        """The duplicate of this item, if there is one.

        The exact match wins, because a row that is the same content is a
        stronger finding than one that is a reworded copy.
        """
        if item.hashes is None or not item.hashes.content_hash:
            return None
        found = await self._index.find(
            content_hash=self.content_key(item),
            near_duplicate=self.near_key(item),
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
            content_hash=self.content_key(item),
            near_duplicate=self.near_key(item),
            origin=origin,
            question_id=item.id,
        )


__all__ = ["DedupeService"]
