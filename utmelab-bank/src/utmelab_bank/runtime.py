"""The runner's wiring. One place that opens the store and the pipeline.

The CLI asks for the parts a command needs, not for everything the bank owns.
A status check must still work when the media token is missing, and a tag run
must not need a figure describer. The two builders below make that explicit:
``open_store_runtime`` is the database half, and ``open_pipeline_runtime`` adds
the source, the text provider and the media branch only when the caller asks.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from utmelab_bank.adapters.catalog import ProductionCatalogReader
from utmelab_bank.adapters.database import bank_client, prod_client
from utmelab_bank.adapters.dedupe_service import DedupeService
from utmelab_bank.adapters.media import (
    HttpMediaFetcher,
    MediaIngestor,
    MediaService,
    PillowMediaValidator,
    create_describer,
    create_media_store,
)
from utmelab_bank.adapters.production import KnownQuestion, ProductionContentReader
from utmelab_bank.adapters.providers import create_text_provider
from utmelab_bank.adapters.sources import create_source
from utmelab_bank.adapters.store import ContentIndexStore, StagingStore
from utmelab_bank.config import Settings
from utmelab_bank.domain.models import CatalogSnapshot, StagingItem
from utmelab_bank.domain.ports import (
    AnswerVerifier,
    CatalogReader,
    ContentIndex,
    Explainer,
    Source,
    Tagger,
)

logger = logging.getLogger(__name__)


class Staging(Protocol):
    """The staging methods the runner uses.

    This is narrower than ``domain.ports.StagingStore`` on purpose: a task
    should not need every store method just to read a state, and a test double
    should not have to pretend to own a database to prove a task loop.
    """

    async def prepare(self) -> None: ...

    async def save(self, item: StagingItem) -> None: ...

    async def load(self, item_id: str) -> StagingItem | None: ...

    async def passage_ids(self) -> frozenset[str]: ...

    async def list_by_state(self, state: str, *, limit: int = 100) -> tuple[StagingItem, ...]: ...

    async def list_by_states(
        self,
        states: Sequence[str],
        *,
        limit: int = 100,
        exam: str | None = None,
        subject: str | None = None,
        year: int | None = None,
    ) -> tuple[StagingItem, ...]: ...

    async def counts_by_state(self) -> dict[str, int]: ...


class Index(ContentIndex, Protocol):
    """The index methods the runner uses, beyond the read-only port."""

    async def remember_many(
        self,
        entries: Sequence[tuple[str, str, str, str]],
        *,
        commit: bool = True,
    ) -> None: ...

    async def forget(self, origin: str) -> None: ...

    async def commit(self) -> None: ...


class ProductionReader(Protocol):
    """What the production content reader has to provide for the index task."""

    def iter_known(self) -> AsyncIterator[KnownQuestion]: ...


@dataclass
class Runtime:
    """Everything an opened run can reach.

    The store fields are always present. The pipeline fields are ``None`` when
    the command did not ask for them, and the task that needs one says so
    clearly through ``require`` instead of failing on an attribute error.
    """

    settings: Settings
    staging: Staging
    index: Index
    catalog_reader: CatalogReader
    production: ProductionReader
    source: Source | None = None
    tagger: Tagger | None = None
    explainer: Explainer | None = None
    verifier: AnswerVerifier | None = None
    ingestor: MediaIngestor | None = None
    media: MediaService | None = None

    _catalogs: dict[tuple[str, str], CatalogSnapshot] = field(default_factory=dict, init=False)
    _closers: list[Callable[[], Awaitable[None]]] = field(default_factory=list, init=False)

    async def catalog_for(self, exam: str, subject: str) -> CatalogSnapshot:
        """The catalog for a scope, read once and reused for the run.

        A batch of rows in one subject asks the same question repeatedly. The
        snapshot is versioned and stable for the run, so reading it once is
        both faster and the honest unit: the tag step validated against this
        version, not against one that changed halfway through.
        """
        key = (exam, subject)
        cached = self._catalogs.get(key)
        if cached is None:
            cached = await self.catalog_reader.snapshot(exam, subject)
            self._catalogs[key] = cached
        return cached

    @property
    def dedupe(self) -> DedupeService:
        """The dedupe step over this run's index. Stateless, so built on use."""
        return DedupeService(self.index)

    def add_closer(self, closer: Callable[[], Awaitable[None]]) -> None:
        """Register something to close when the run ends, in reverse order."""
        self._closers.append(closer)

    async def close(self) -> None:
        """Close every resource, newest first, without hiding the first error.

        A close failure is logged and the remaining resources are still
        closed. The run's result is what the caller is waiting for, and a
        failed socket close should not replace it with a traceback.
        """
        while self._closers:
            closer = self._closers.pop()
            try:
                await closer()
            except Exception:
                logger.exception("closing a run resource failed")


def require[T](value: T | None, name: str) -> T:
    """Return a configured part, or say which part the command is missing."""
    if value is None:
        raise RuntimeError(f"this command needs the {name}, and the run did not open it")
    return value


@asynccontextmanager
async def open_store_runtime(settings: Settings) -> AsyncIterator[Runtime]:
    """Open the two databases and the readers the store tasks need.

    This does not open a source, a model, or a media store. That is what lets
    ``status`` and ``index`` work when only the database half is configured.
    """
    prod = prod_client(settings)
    bank = bank_client(settings)
    runtime = Runtime(
        settings=settings,
        staging=StagingStore(bank),
        index=ContentIndexStore(bank),
        catalog_reader=ProductionCatalogReader(prod),
        production=ProductionContentReader(prod),
    )
    runtime.add_closer(bank.close)
    runtime.add_closer(prod.close)
    try:
        await runtime.staging.prepare()
        yield runtime
    finally:
        await runtime.close()


@asynccontextmanager
async def open_pipeline_runtime(
    settings: Settings,
    *,
    source_name: str | None = None,
    fixture_dir: Path | None = None,
    provider_name: str | None = None,
    media: bool = False,
    text: bool = False,
    image: bool = False,
) -> AsyncIterator[Runtime]:
    """Open the store half, then only the pipeline parts the command named.

    ``media`` opens the store and the fetcher, which is what the scrape run
    needs to capture figure bytes. ``text`` opens the tag, explain and verify
    provider. ``image`` opens the two-witness describer and the media service,
    which is what the later processing run needs. ``image`` implies ``media``.
    """
    async with open_store_runtime(settings) as runtime:
        if source_name is not None:
            runtime.source = create_source(source_name, fixture_dir=fixture_dir)
            close = getattr(runtime.source, "close", None)
            if callable(close):
                runtime.add_closer(close)

        if media or image:
            store = create_media_store(settings)
            fetcher = HttpMediaFetcher()
            runtime.ingestor = MediaIngestor(fetcher, PillowMediaValidator(), store)
            runtime.add_closer(fetcher.close)
            close = getattr(store, "close", None)
            if callable(close):
                runtime.add_closer(close)

        if text:
            if provider_name is None:
                raise RuntimeError("a text step needs a provider")
            provider = create_text_provider(provider_name, settings=settings)
            runtime.tagger = provider
            runtime.explainer = provider
            runtime.verifier = provider

        if image:
            if provider_name is None:
                raise RuntimeError("the figure describer needs a provider")
            ingestor = runtime.ingestor
            if ingestor is None:
                raise RuntimeError("the figure describer needs the media branch")
            describer = create_describer(
                provider=provider_name,
                model=settings.ai_image_model,
                second_model=settings.ai_image_second_model,
            )
            runtime.media = MediaService(ingestor, describer)

        yield runtime


__all__ = [
    "Index",
    "ProductionReader",
    "Runtime",
    "Staging",
    "open_pipeline_runtime",
    "open_store_runtime",
    "require",
]
