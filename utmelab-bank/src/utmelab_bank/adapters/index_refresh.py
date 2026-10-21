"""Refreshing the content index from production.

The index is a cache of what production holds, so it has to be brought up to
date. The refresh reads the served bank's questions, computes the
near-duplicate fingerprint for each, and writes both fingerprints into the
bank's index.

It runs on a schedule, not per item, because the cost of a refresh is the
size of the bank and the benefit is a lookup on every item.
"""

from __future__ import annotations

from utmelab_bank.adapters.production import ProductionContentReader
from utmelab_bank.adapters.store.index import (
    BATCH,
    PRODUCTION,
    ContentIndexStore,
)


class IndexRefresher:
    """Loads what production holds into the bank's index."""

    def __init__(self, index: ContentIndexStore, reader: ProductionContentReader) -> None:
        self._index = index
        self._reader = reader

    async def refresh(self) -> int:
        """Reload the production half of the index, and return the count.

        The production half is dropped first, so a question that production
        has deleted does not stay in the index forever and refuse content
        that is no longer a duplicate of anything.

        The rows are written in batches. The round trip to Turso is about a
        second, so one write per row would take an hour on a bank of two
        thousand questions, and a minute in batches.
        """
        await self._index.forget(PRODUCTION)
        count = 0
        batch: list[tuple[str, str, str, str]] = []
        async for known in self._reader.iter_known():
            batch.append(
                (
                    known.content_hash,
                    known.near_duplicate,
                    PRODUCTION,
                    known.question_id,
                )
            )
            if len(batch) >= BATCH:
                await self._index.remember_many(batch, commit=False)
                count += len(batch)
                batch = []
        if batch:
            await self._index.remember_many(batch, commit=False)
            count += len(batch)
        await self._index.commit()
        return count


__all__ = ["IndexRefresher"]
