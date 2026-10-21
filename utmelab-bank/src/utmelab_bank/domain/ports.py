"""Ports. The core depends on these shapes, never on a concrete adapter."""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .capabilities import (
    DescribeImageRequest,
    ExplainRequest,
    TagRequest,
    VerifyAnswerRequest,
)
from .dedupe import Duplicate
from .models.common import (
    CatalogSnapshot,
    Coverage,
    MediaAsset,
    Producer,
    Scope,
    SourceItem,
    SourceProfile,
    StagingItem,
)
from .models.proposals import (
    AnswerVerdict,
    Explanation,
    ImageDescription,
    TagProposal,
)


@runtime_checkable
class Source(Protocol):
    profile: SourceProfile

    async def probe(self, scope: Scope) -> Coverage: ...

    def fetch(self, scope: Scope) -> AsyncIterator[SourceItem]: ...

    def adapt(self, item: SourceItem, catalog: CatalogSnapshot) -> StagingItem: ...

    def validate(self, item: SourceItem) -> list[str]: ...


@runtime_checkable
class ImageDescriber(Protocol):
    producer: Producer

    async def describe(self, request: DescribeImageRequest) -> ImageDescription: ...


@runtime_checkable
class Explainer(Protocol):
    producer: Producer

    async def explain(self, request: ExplainRequest) -> Explanation: ...


@runtime_checkable
class Tagger(Protocol):
    producer: Producer

    async def tag(self, request: TagRequest) -> TagProposal: ...


@runtime_checkable
class AnswerVerifier(Protocol):
    producer: Producer

    async def verify(self, request: VerifyAnswerRequest) -> AnswerVerdict: ...


@runtime_checkable
class CatalogReader(Protocol):
    """Reads catalog from PRODUCTION DB for AI context."""

    async def snapshot(self, exam: str, subject: str) -> CatalogSnapshot: ...


@runtime_checkable
class MediaStore(Protocol):
    async def put(
        self,
        data: bytes,
        *,
        mime: str,
        source_url: str | None = None,
    ) -> MediaAsset: ...

    async def read(self, asset_id: str) -> bytes: ...

    async def exists(self, asset_id: str) -> bool: ...


@runtime_checkable
class StagingStore(Protocol):
    """Our minimal staging DB - 1 table for items, 1 for media."""

    async def save(self, item: StagingItem) -> None: ...

    async def load(self, item_id: str) -> StagingItem | None: ...

    async def transition(
        self, item_id: str, to_state: str, *, error: str | None = None
    ) -> StagingItem: ...

    async def list_by_state(self, state: str, *, limit: int = 100) -> tuple[StagingItem, ...]: ...


@runtime_checkable
class ContentIndex(Protocol):
    """What the bank already knows about, in a form a lookup can use.

    The index holds the two fingerprints of every known question, so a
    duplicate check is a lookup and not a scan of the whole bank.
    """

    async def remember(
        self,
        *,
        content_hash: str,
        near_duplicate: str,
        origin: str,
        question_id: str,
    ) -> None: ...

    async def find(self, *, content_hash: str, near_duplicate: str) -> Duplicate | None: ...

    async def exact_match(self, content_hash: str) -> str | None: ...

    async def near_matches(self, near_duplicate: str) -> tuple[str, ...]: ...

    async def count(self, origin: str | None = None) -> int: ...


class MediaFetcher(Protocol):
    """Downloads media from source URLs."""

    async def fetch(self, url: str) -> bytes: ...


@runtime_checkable
class MediaValidator(Protocol):
    """Validates downloaded media (MIME, dimensions, corruption)."""

    async def validate(self, data: bytes, mime: str | None) -> MediaAsset: ...
