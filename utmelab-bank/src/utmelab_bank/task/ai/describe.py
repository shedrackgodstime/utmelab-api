"""ai-describe: ask the model what one fetched figure shows.

One media row in, one described row out. Reads the blob bytes the fetch task
landed in the clone plus the owning question's stem for context, asks the
image model (or the text model when no image model is configured), and stamps
``description`` + ``description_model`` with ``status='described'``.

A row with no bytes is skipped: describe needs the figure, and a row whose
fetch failed is fetch's problem, not ours.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.task.ai.describe_tasks import describe_figure
from utmelab_bank.task.ai.providers import build_provider
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["AiDescribe", "describe_one"]

log = logging.getLogger(__name__)


@registered
class AiDescribe:
    """Ask the model what one fetched figure shows."""

    name = "ai-describe"
    produces = "description"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Ask the model to describe one fetched figure."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return await describe_one(row, ctx)

    async def collect(self, _ctx: TaskContext) -> list[RowOutcome]:
        return []


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return value


async def describe_one(row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
    """Describe one media row and stamp the description onto it."""
    row_id = str(row.get("id", ""))
    if not row_id:
        return ctx.skip(row_id, "no_id", "the media row has no id")

    if row.get("description"):
        return ctx.skip(row_id, "already_described", "this figure already has a description")

    blob_rel = str(row.get("blob_path") or "")
    if not blob_rel:
        return ctx.skip(row_id, "no_bytes", "this figure has no fetched bytes yet")

    if ctx.dry_run or ctx.config.sink == "json":
        return ctx.ok(row_id)

    blob_path = ctx.config.repo.media_repo / blob_rel
    if not blob_path.is_file():
        return ctx.skip(row_id, "blob_missing", f"blob not on disk at {blob_rel}")

    stem, options = await _question_context(ctx, row)
    image_model = ctx.config.ai_image_model or None
    provider = build_provider(ctx.config, "opencode", model=image_model)
    try:
        result = await describe_figure(provider, row, stem, options)
    finally:
        await provider.aclose()

    if result.error:
        return ctx.fail(row_id, "ai_failed", result.error, retryable=True)
    if not result.description:
        return ctx.skip(row_id, "empty_description", "the model returned no usable description")

    await ctx.repo.update(
        "media",
        row_id,
        {
            "description": result.description,
            "description_model": provider.name,
            "status": "described",
            "updated_at": now_iso(),
        },
    )

    log.info("ai-describe %s: %s (%d chars)", row_id, result.figure_kind, len(result.description))
    return ctx.ok(row_id)


async def _question_context(ctx: TaskContext, row: dict[str, Any]) -> tuple[str, list[str]]:
    """The owning question's stem and option texts, for the prompt's context."""
    question_id = str(row.get("question_id") or "")
    if not question_id:
        return ("", [])
    found = await ctx.repo.rows("questions", f"id={question_id}")
    if not found:
        return ("", [])
    question = found[0]
    stem = str(question.get("text") or "")
    texts: list[str] = []
    for entry in _loads(question.get("options"), []):
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        label = str(entry.get("id", ""))
        text = str(body.get("text", "")) if isinstance(body, dict) else str(body or "")
        texts.append(f"{label}) {text}".strip())
    return (stem, texts)
