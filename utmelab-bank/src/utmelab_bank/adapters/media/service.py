"""The media branch, composed.

`domain/state.py` declares two ways out of `catalogued`:

    catalogued -> media_ready -> described -> enriched
    catalogued -> enriched            (the media step is optional)

This is the first. The bytes are captured after the gate and the duplicate
check, in the dedicated capture step, so a row the scrape refuses never
uploads a figure. This step only moves the row through the states and runs
the witnesses; it never touches the source. An item with no assets is
returned untouched, so the optional path stays the caller's choice rather
than a special case buried here.
"""

from __future__ import annotations

from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.domain.ports import ImageDescriber

from .describe import ImageDescriberService
from .ingest import MediaIngestor
from .ocr_space import OcrSpaceClient


class MediaService:
    """Drive captured assets through media_ready and described.

    The describer is wired to the ingestor's store, so the bytes the scrape
    captured are the bytes the witnesses see.
    """

    def __init__(
        self,
        ingestor: MediaIngestor,
        describer: ImageDescriber,
        ocr: OcrSpaceClient | None = None,
    ) -> None:
        self._ingestor = ingestor
        self._describer = ImageDescriberService(
            describer,
            reader=ingestor.store,
            ocr=ocr,
        )

    async def apply(self, item: StagingItem, *, capture: bool = False) -> StagingItem:
        """Finalize a captured row.

        ``capture`` is for a one-run caller and for tests. The normal pipeline
        captures in the dedicated capture step and calls this without it.

        The method is resumable. A row that crashed after the state moved to
        ``media_ready`` is described without asking the state machine to move
        it there a second time. A row with no assets is left at ``catalogued``
        so the caller can take the optional path to enrichment; a row already
        at ``media_ready`` has no optional path, so it is described and moves
        on even when every ref was skipped.
        """
        if capture:
            item = await self._ingestor.capture_refs(item)
        if item.state is State.CATALOGUED:
            if not item.media_assets:
                return item
            item = item.transition_to(State.MEDIA_READY)
        if item.state is State.MEDIA_READY:
            return await self._describer.describe(item)
        return item


__all__ = ["MediaService"]
