"""Whether a question's figures are all actually reachable.

The pipeline probed every image url with a HEAD request at harvest time, inside
the gate. That made scraping depend on the image host being up, so a slow or
rate-limited CDN refused questions for a reason that has nothing to do with the
questions.

Media presence is a separate task here. It finds the figures, records them, and
leaves fetching to ``media_fetch``.
"""

from __future__ import annotations

import hashlib
from typing import Any

from utmelab_bank.task.base import TaskContext, registered

__all__ = ["MediaPresence"]


@registered
class MediaPresence:
    """Records every figure a question references, into the media lane."""

    name = "media-discover"
    produces = "status"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Record every figure url a question references, without fetching it."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> Any:
        return await discover(row, ctx)

    async def collect(self, _ctx: TaskContext) -> list[Any]:
        return []


async def discover(row: dict[str, Any], ctx: TaskContext) -> Any:
    """Insert a media row per distinct figure this question carries.

    The identity is the source url, not the row id. A re-run after an upload
    sees our own ``/media/...`` path in the question and must not mistake it for
    a new provider figure, and a changed id scheme must not duplicate a figure
    that is already recorded. Both are the same check: what does this question
    already have?
    """
    from utmelab_bank.model.base import now_iso

    row_id = str(row.get("id", ""))
    urls = _figure_urls(row)
    if not urls:
        return ctx.ok(row_id)

    known = {
        str(existing.get("source_url") or "")
        for existing in await ctx.repo.rows("media", f"question_id={row_id}")
    }
    fresh = [url for url in urls if url not in known]
    if not fresh:
        return ctx.skip(
            row_id, "already_discovered", "this question's figures are already recorded"
        )

    stamp = now_iso()
    rows = [
        {
            "id": _id_for(url),
            "source_url": url,
            "question_id": row_id,
            "status": "discovered",
            "sha256": None,
            "blob_path": None,
            "derived_path": None,
            "media_url": None,
            "description": None,
            "description_model": None,
            "bytes": None,
            "attempts": 0,
            "error": None,
            "next_retry_at": None,
            "run_id": ctx.run.id,
            "created_at": stamp,
            "updated_at": stamp,
        }
        for url in fresh
    ]
    if not ctx.dry_run:
        await ctx.repo.insert_many("media", rows)
    return ctx.ok(row_id)


def _id_for(url: str) -> str:
    """A stable row id from the source url.

    The file name alone can collide across hosts and can carry characters a
    url allows but a path does not. The hash is the same length for every
    figure and never depends on how a provider names its files.
    """
    return f"m_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:32]}"


def _figure_urls(row: dict[str, Any]) -> list[str]:
    """Distinct image urls on a question row, from its two json columns."""
    from utmelab_bank.rules import load_json_column

    urls: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("kind") == "image" and value.get("url"):
                url = str(value["url"])
                # Our own path means the figure is already published. Treating
                # it as a new provider url would duplicate every uploaded
                # figure the next time the media goal runs.
                if not url.startswith("/media/"):
                    urls.append(url)
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    for column in ("inline", "options"):
        raw = row.get(column)
        if raw in (None, ""):
            continue
        walk(load_json_column(row, column, []))

    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered
