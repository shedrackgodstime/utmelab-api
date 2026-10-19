"""media_fetch: download each discovered figure's bytes into the media clone.

``media-discover`` records figure urls; this task fetches them. One blob per
distinct figure, addressed by sha256, so re-fetching the same url is
idempotent: the hash already on disk means nothing to download.

Fetches are spaced and retried through :class:`utmelab_bank.source.http.PoliteSession`,
so a slow image host never blocks the whole run. Network failures are per-row
retries, not broken runs.

Writes nothing unless the sink is the database (``--sink db``). With ``--sink json``
the task is a no-op, matching the json sink's read-only contract.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from utmelab_bank.blob.gitstore import GitStore
from utmelab_bank.blob.paths import extension_for
from utmelab_bank.errors import BlobError
from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.source.http import PoliteSession
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["MediaFetch", "fetch_one"]

log = logging.getLogger(__name__)

#: How many media rows one fetch run processes. Bounded so a bad url list is a
#: mistake on part of one, and so the run is restartable at a known point.
BATCH: int = 200


@registered
class MediaFetch:
    """Download each discovered figure into the media clone, addressed by content."""

    name = "media-fetch"
    produces = "blob_path"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Download each discovered figure's bytes into the media clone."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return await fetch_one(row, ctx)

    async def collect(self, _ctx: TaskContext) -> list[RowOutcome]:
        return []


async def fetch_one(row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
    """Fetch one figure's bytes into the media clone and stamp the media row."""

    row_id = str(row.get("id", ""))
    if not row_id:
        return ctx.skip(row_id, "no_id", "the media row has no id")

    source_url = str(row.get("source_url") or "")
    if not source_url:
        return ctx.skip(row_id, "no_source_url", "the media row has no source_url")

    # Already fetched, but only if the bytes are still on disk. The row records
    # a blob_path, and a fresh CI runner rebuilds the clone from the remote, so
    # a row can claim to be fetched while this clone has never seen the figure.
    # Trusting the row alone made every retry after a failed upload skip here
    # and then fail in upload with "blob is not in the clone".
    store = GitStore(
        root=ctx.config.repo.media_repo,
        remote=ctx.config.media_remote,
        branch=ctx.config.media_branch,
    )
    cached_digest = str(row.get("sha256") or "")
    cached_path = str(row.get("blob_path") or "")
    cached_ext = Path(cached_path).suffix if cached_path else ""
    if cached_digest and cached_ext and store.has_blob(cached_digest, cached_ext):
        return ctx.skip(row_id, "already_fetched", "this figure's bytes are already in the clone")

    if ctx.dry_run or ctx.config.sink == "json":
        return ctx.ok(row_id)

    # Ensure the clone exists. Idempotent: a no-op when the clone is already there.
    try:
        store.ensure_cloned()
    except BlobError as exc:
        return ctx.fail(row_id, "no_media_clone", str(exc), retryable=False)

    # Fetch the bytes. Network failures are per-row retries, not broken runs.
    try:
        async with PoliteSession(ctx.config) as session:
            response = await session.get(source_url)
        data = response.content
    except Exception as exc:  # noqa: BLE001 — any network or filesystem error is a retryable row failure
        return ctx.fail(row_id, "fetch_failed", str(exc), retryable=True)

    content_type = response.headers.get("content-type")
    ext = extension_for(source_url, content_type, data)
    digest, blob_path, _our_path = store.write_blob(data, ext)

    stamp = now_iso()
    await ctx.repo.update(
        "media",
        row_id,
        {
            "blob_path": str(blob_path.relative_to(store.root)),
            "sha256": digest,
            "bytes": len(data),
            # The question keeps the provider's full url until an upload actually
            # publishes our own copy. Stamping our file name here would
            # point it at a file nothing serves yet. Upload replaces this value
            # with our file name once the bytes are pushed.
            "media_url": source_url,
            "status": "fetched",
            "error": None,
            "next_retry_at": None,
            "updated_at": stamp,
        },
    )

    log.info("media-fetch %s: %d bytes, sha %s", row_id, len(data), digest)
    return ctx.ok(row_id)
