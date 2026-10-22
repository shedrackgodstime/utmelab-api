"""Media ingestion: fetch, validate, store, and attach to staging items.

The figure rule, in one place.

A source offers an image at a url. The bank tries to own it: it fetches the
bytes, validates them, and stores them. When the store hands back a url the
bank can serve, the bank owns the asset. That url replaces the source url in
every image inline that pointed at it, and the asset drops its ``source_url``
so the row can no longer fall back to a host that may die.

When the bank cannot own the asset the ref is **skipped** and the inline
keeps the full source url. That is the case for an optional media entry that
fails to fetch or validate, and for a store that cannot hand back a servable
url. A ``required`` entry that fails is not skipped: it fails the row, because
a question that needs its figure and does not have it is not a question the
bank can serve.

Attaching an asset changes the bundle fingerprint, and swapping a url changes
the content fingerprint too, so the row is re-stamped before it moves on.
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime

import httpx
from PIL import Image

from utmelab_bank.domain.enums import InlineKind, State
from utmelab_bank.domain.models import MediaAsset, RichText, StagingItem
from utmelab_bank.domain.ports import MediaFetcher, MediaStore, MediaValidator


class HttpMediaFetcher(MediaFetcher):
    """Fetch media bytes via HTTP with size limit and timeout."""

    def __init__(
        self,
        *,
        max_bytes: int = 10_000_000,  # 10 MB
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "UTME-Lab-MediaFetcher/1.0"},
        )

    async def fetch(self, url: str) -> bytes:
        resp = await self._client.get(url)
        resp.raise_for_status()
        content = resp.content
        if len(content) > self.max_bytes:
            raise ValueError(f"Media exceeds size limit ({self.max_bytes} bytes)")
        return content

    async def close(self) -> None:
        await self._client.aclose()


class PillowMediaValidator(MediaValidator):
    """Validate media using Pillow (MIME sniff, decode, dimensions).

    The asset it returns is a placeholder in the one field the store owns:
    the storage url and the fetch time. Everything the store does not
    recompute comes from the bytes, and the store is what replaces those two.
    """

    async def validate(self, data: bytes, mime: str | None = None) -> MediaAsset:
        sniffed = mime or self._sniff_mime(data)
        if sniffed is None:
            raise ValueError("Could not determine MIME type")

        try:
            img = Image.open(io.BytesIO(data))
            img.verify()  # Verify integrity
            img = Image.open(io.BytesIO(data))  # Reopen after verify
            width, height = img.size
            detected = Image.MIME.get(img.format) if img.format else None
        except Exception as e:
            raise ValueError(f"Invalid image data: {e}") from e

        return MediaAsset(
            asset_id=hashlib.sha256(data).hexdigest(),
            mime=detected or sniffed,
            byte_size=len(data),
            width=width,
            height=height,
            storage_url="pending:the-store-fills-this",
            source_url=None,
            fetched_at=datetime.now(UTC),
            required=True,
            readable=True,
        )

    def _sniff_mime(self, data: bytes) -> str | None:
        """Sniff MIME type from magic bytes."""
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
            return "image/gif"
        if data.startswith(b"RIFF") and b"WEBP" in data[:12]:
            return "image/webp"
        if data.startswith(b"\x00\x00\x00\x0c") and b"ftyp" in data[4:12]:
            return "image/heic"
        return None


class MediaIngestor:
    """Ingest media refs into assets and attach to staging items."""

    def __init__(
        self,
        fetcher: MediaFetcher,
        validator: MediaValidator,
        store: MediaStore,
    ) -> None:
        self.fetcher = fetcher
        self.validator = validator
        self.store = store

    async def capture_refs(self, item: StagingItem) -> StagingItem:
        """Fetch and store every media ref, without moving the row.

        This runs after the gate and the duplicate check, so a row that will
        not be kept never uploads a byte. The row keeps its state and carries
        the assets; the later media step only finalizes and describes them.

        A ref the bank cannot ingest is skipped when it is optional and fails
        the row when it is required. The owned urls are collected as we go, so
        the swap and the fingerprint see the same set of assets.
        """
        if not item.media_refs:
            return item

        assets: list[MediaAsset] = []
        owned: dict[str, str] = {}
        for ref in item.media_refs:
            source_url = str(ref.source_url)
            try:
                data = await self.fetcher.fetch(source_url)
                checked = await self.validator.validate(data, ref.mime)
                asset = await self.store.put(
                    data,
                    mime=checked.mime,
                    source_url=source_url,
                )
            except Exception:
                if ref.required:
                    raise
                continue

            if self.store.can_serve(asset.storage_url):
                # The bank can serve it, so it owns it. The inline records the
                # stored name; the serving layer composes the public url.
                owned[source_url] = asset.storage_url
                assets.append(asset.model_copy(update={"source_url": None}))
            else:
                # Stored but not servable yet: the row keeps the source url.
                assets.append(asset)

        # The refs have done their job. Keeping them would make a later media
        # step fetch the source again, which is the one thing capture exists to
        # avoid.
        updated = item.model_copy(
            update={"media_assets": tuple(assets), "media_refs": ()},
        )
        updated = _swap_owned_urls(updated, owned)
        return updated.stamp_hashes()

    async def ingest_refs(self, item: StagingItem) -> StagingItem:
        """Capture and move to ``media_ready``. The combined path, for one run."""
        captured = await self.capture_refs(item)
        return captured.transition_to(State.MEDIA_READY)


def _swap_owned_urls(item: StagingItem, owned: dict[str, str]) -> StagingItem:
    """Point every image inline at the bank's stored name.

    The inline carries the name, not a url. The serving layer decides the host,
    so a domain move does not rewrite a single row.
    """
    if not owned:
        return item

    def rewrite(text: RichText) -> RichText:
        inline = tuple(
            one.model_copy(update={"url": owned[one.url]})
            if one.kind is InlineKind.IMAGE and one.url is not None and one.url in owned
            else one
            for one in text.inline
        )
        return text.model_copy(update={"inline": inline})

    content = item.content
    swapped = content.model_copy(
        update={
            "stem": rewrite(content.stem),
            "options": tuple(
                option.model_copy(update={"text": rewrite(option.text)})
                for option in content.options
            ),
        }
    )
    return item.model_copy(update={"content": swapped})


async def ingest_media_task(
    item: StagingItem,
    fetcher: MediaFetcher,
    validator: MediaValidator,
    store: MediaStore,
) -> StagingItem:
    """Task: ingest media refs for a staging item."""
    ingestor = MediaIngestor(fetcher, validator, store)
    return await ingestor.ingest_refs(item)


__all__ = [
    "HttpMediaFetcher",
    "MediaFetcher",
    "MediaIngestor",
    "MediaValidator",
    "PillowMediaValidator",
    "ingest_media_task",
]
