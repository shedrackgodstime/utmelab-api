"""The media branch, composed.

`domain/state.py` declares two ways out of `catalogued`:

    catalogued -> media_ready -> described -> enriched
    catalogued -> enriched            (the media step is optional)

This is the first. The bytes were captured in the scrape run, because that is
the only moment the source is guaranteed alive. This step only moves the row
through the states and runs the witnesses; it never touches the source. An
item with no assets is returned untouched, so the optional path stays the
caller's choice rather than a special case buried here.
"""

from __future__ import annotations

from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.domain.ports import ImageDescriber

from .describe import ImageDescriberService
from .ingest import MediaIngestor


class MediaService:
    """Drive captured assets through media_ready and described.

    The describer is wired to the ingestor's store, so the bytes the scrape
    captured are the bytes the witnesses see.
    """

    def __init__(self, ingestor: MediaIngestor, describer: ImageDescriber) -> None:
        self._ingestor = ingestor
        self._describer = ImageDescriberService(describer, reader=ingestor.store)

    async def apply(self, item: StagingItem, *, capture: bool = False) -> StagingItem:
        """Finalize a captured row.

        ``capture`` is for a one-run caller and for tests. The two-run pipeline
        captures in the scrape run and calls this without it.
        """
        if capture:
            item = await self._ingestor.capture_refs(item)
        if not item.media_assets:
            return item
        ready = item.transition_to(State.MEDIA_READY)
        return await self._describer.describe(ready)


__all__ = ["MediaService"]
