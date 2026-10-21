"""The media branch, composed.

`domain/state.py` declares two ways out of `catalogued`:

    catalogued -> media_ready -> described -> enriched
    catalogued -> enriched            (the media step is optional)

This is the first. It runs the ingest and then the describe, in that order,
because the describe needs the assets the ingest attaches. An item with no
media refs is returned untouched, so the optional path stays the caller's
choice rather than a special case buried here.
"""

from __future__ import annotations

from utmelab_bank.domain.models import StagingItem

from .describe import ImageDescriberService
from .ingest import MediaIngestor


class MediaService:
    """Drive one item through media_ready and described."""

    def __init__(self, ingestor: MediaIngestor, describer: ImageDescriberService) -> None:
        self._ingestor = ingestor
        self._describer = describer

    async def apply(self, item: StagingItem) -> StagingItem:
        if not item.media_refs:
            return item
        ingested = await self._ingestor.ingest_refs(item)
        return await self._describer.describe(ingested)


__all__ = ["MediaService"]
