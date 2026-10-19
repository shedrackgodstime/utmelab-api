"""media-upload: publish fetched figures and point each question at our copy.

The media project holds the bytes; the bank holds ``/media/ab/<sha>.<ext>``,
never a gitlab url. The api serves that path and keeps the credential, so moving
the project later is a configuration change, not a rewrite of every question.

One commit, one push. The working tree is the pending batch, so a run that dies
before the push leaves its work where the next run finds it, and the next run
stages the same bytes.

The content hash is an identity, not a checksum. It is stamped once and edits
preserve it (the same rule ``ai-explain`` follows). Rewriting a provider url to
our own path therefore keeps the hash, and every verification written against
the question still joins. Re-hashing here would orphan the human verdicts that
are the whole point of the bank.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from utmelab_bank.blob.gitstore import GitStore
from utmelab_bank.blob.paths import url_for
from utmelab_bank.errors import BlobError
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.rules import load_json_column
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["MediaUpload", "upload_batch"]

log = logging.getLogger(__name__)

_COMMIT_MESSAGE = "media: publish fetched figures"


@registered
class MediaUpload:
    """Publish fetched figures and rewrite the questions that reference them."""

    name = "media-upload"
    produces = "media_url"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = False
    description = "Publish fetched figures and point each question at our copy."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return ctx.skip(str(row.get("id", "")), "batch_task", "media-upload runs as a batch")

    async def collect(self, ctx: TaskContext) -> list[RowOutcome]:
        return await upload_batch(ctx)


def _selector(ctx: TaskContext) -> str:
    """The batch is always fetched figures that have not been published.

    The caller's ``--where`` narrows that batch; it never widens it, so an
    upload run cannot pick a row with no bytes and then report a mysterious
    failure.
    """
    base = "not uploaded and has blob"
    asked = (ctx.where or "all").strip().lower()
    if asked in ("", "all"):
        return base
    return f"{asked} and {base}"


def _replace(value: Any, source: str, target: str) -> tuple[Any, bool]:
    """Replace every exact occurrence of ``source`` in a parsed json value."""
    if isinstance(value, str):
        return (target, True) if value == source else (value, False)
    if isinstance(value, list):
        changed = False
        items = []
        for item in value:
            new, did = _replace(item, source, target)
            items.append(new)
            changed = changed or did
        return items, changed
    if isinstance(value, dict):
        changed = False
        mapping = {}
        for key, item in value.items():
            new, did = _replace(item, source, target)
            mapping[key] = new
            changed = changed or did
        return mapping, changed
    return value, False


def _rewrite_question(row: dict[str, Any], source: str, target: str) -> dict[str, str] | None:
    """The json columns that now point at our copy, or ``None`` when nothing did.

    The content hash is deliberately not in the result: it is the row's identity
    and survives the address change.
    """
    changes: dict[str, str] = {}
    for column in ("inline", "options", "explanation"):
        parsed = load_json_column(row, column, [])
        new, changed = _replace(parsed, source, target)
        if changed:
            changes[column] = json.dumps(new, separators=(",", ":"))
    return changes or None


async def upload_batch(ctx: TaskContext) -> list[RowOutcome]:
    """Publish every selected figure, then rewrite the questions that use them."""
    rows = await ctx.repo.rows("media", _selector(ctx), limit=ctx.limit)
    if not rows:
        return []
    if ctx.dry_run or ctx.config.sink == "json":
        return [ctx.ok(str(row.get("id", ""))) for row in rows]

    store = GitStore(
        root=ctx.config.repo.media_repo,
        remote=ctx.config.media_remote,
        branch=ctx.config.media_branch,
    )
    if not store.push_enabled(ctx.config.media_upload_enabled):
        return [
            ctx.skip(
                str(row.get("id", "")),
                "push_disabled",
                "set UTMELAB_BANK_MEDIA_UPLOAD_ENABLED=1 and a media remote",
            )
            for row in rows
        ]

    try:
        store.ensure_cloned()
        store.pull_ff_only()
    except BlobError as exc:
        return [
            ctx.fail(str(row.get("id", "")), "no_media_clone", str(exc), retryable=False)
            for row in rows
        ]

    prepared, outcomes = _prepare(store, rows, ctx)
    if not prepared:
        return outcomes

    staged = store.stage_all()
    if staged:
        store.commit(_COMMIT_MESSAGE, amend=store.has_commits())
    try:
        store.push(allowed=ctx.config.media_upload_enabled)
    except BlobError as exc:
        outcomes.extend(
            ctx.fail(str(row.get("id", "")), "push_failed", str(exc), retryable=True)
            for row in prepared
        )
        return outcomes

    outcomes.extend(await _publish(ctx, prepared))
    return outcomes


def _prepare(
    store: GitStore, rows: list[dict[str, Any]], ctx: TaskContext
) -> tuple[list[dict[str, Any]], list[RowOutcome]]:
    """Keep rows whose bytes are really on disk; explain the rest."""
    prepared: list[dict[str, Any]] = []
    outcomes: list[RowOutcome] = []
    for row in rows:
        row_id = str(row.get("id", ""))
        digest = str(row.get("sha256") or "")
        blob_rel = str(row.get("blob_path") or "")
        extension = Path(blob_rel).suffix
        if not digest or not extension:
            outcomes.append(
                ctx.fail(row_id, "bad_address", "the media row has no usable hash or extension")
            )
            continue
        try:
            blob = store.blob_path(digest, extension)
        except BlobError as exc:
            outcomes.append(ctx.fail(row_id, "bad_address", str(exc), retryable=False))
            continue
        if not blob.is_file():
            outcomes.append(
                ctx.fail(row_id, "blob_missing", f"bytes are not on disk at {blob_rel}")
            )
            continue
        prepared.append(row)
    return prepared, outcomes


async def _publish(ctx: TaskContext, prepared: list[dict[str, Any]]) -> list[RowOutcome]:
    """After a successful push: rewrite each question, then stamp the media row."""
    outcomes: list[RowOutcome] = []
    for row in prepared:
        row_id = str(row.get("id", ""))
        digest = str(row.get("sha256") or "")
        extension = Path(str(row.get("blob_path") or "")).suffix
        target = url_for(digest, extension)
        source = str(row.get("source_url") or "")
        question_id = str(row.get("question_id") or "")

        if not question_id:
            outcomes.append(ctx.fail(row_id, "no_question", "the media row has no question_id"))
            continue
        questions = await ctx.repo.rows("questions", f"id={question_id}")
        if not questions:
            outcomes.append(
                ctx.fail(row_id, "question_missing", f"question {question_id} is not in this lane")
            )
            continue

        changes = _rewrite_question(questions[0], source, target) if source else None
        if changes:
            await ctx.repo.update("questions", question_id, changes)
        await ctx.repo.update(
            "media",
            row_id,
            {
                "media_url": target,
                "status": "uploaded",
                "error": None,
                "next_retry_at": None,
            },
        )
        log.info("media-upload %s: %s -> %s", row_id, source, target)
        outcomes.append(ctx.ok(row_id))
    return outcomes
