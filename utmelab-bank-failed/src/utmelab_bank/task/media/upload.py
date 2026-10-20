"""media-upload: publish fetched figures and point each question at our copy.

The media project holds the bytes; the bank records the file name
``<sha>.<ext>``, never a gitlab url and never a repo or route prefix. The api
decides how to reach the file, and keeps the credential, so moving the project
later is a configuration change, not a rewrite of every question.

One commit, one push. The working tree is the pending batch, so a run that dies
before the push leaves its work where the next run finds it, and the next run
stages the same bytes.

The content hash is an identity, not a checksum. It is stamped once and edits
preserve it (the same rule ``ai-explain`` follows). Rewriting a provider url to
our own file name therefore keeps the hash, and every verification written against
the question still joins. Re-hashing here would orphan the human verdicts that
are the whole point of the bank.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from utmelab_bank.blob.gitstore import BlobRef, GitStore
from utmelab_bank.blob.paths import name_for
from utmelab_bank.errors import BlobError, GitAuthError
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.rules import load_json_column
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["MediaUpload", "upload_batch"]

log = logging.getLogger(__name__)


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
    and survives the name change.
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

    prepared, outcomes = _prepare(store, rows, ctx)
    if not prepared:
        return outcomes

    # One publish for the whole batch, so one failure is one reason for every
    # row in it. The rows still each carry it, because a row that does not say
    # why it failed is a row the next run picks up with nothing to go on.
    try:
        report = store.publish(_blob_refs(prepared), allowed=ctx.config.media_upload_enabled)
    except BlobError as exc:
        code = "git_auth_failed" if isinstance(exc, GitAuthError) else "push_failed"
        outcomes.extend(
            ctx.fail(
                str(row.get("id", "")),
                code,
                str(exc),
                # An auth failure is the one case that will not fix itself, and
                # retrying it would spend the run's budget to arrive at the same
                # answer. Everything else clears on its own.
                retryable=exc.is_retryable,
            )
            for row in prepared
        )
        return outcomes

    log.info(
        "media-upload: %d figures, %d bytes, %d attempt(s)%s at %s",
        report.files,
        report.bytes_added,
        report.attempts,
        " after recovering a lease" if report.recovered else "",
        report.sha[:12],
    )
    outcomes.extend(await _publish(ctx, prepared))
    return outcomes


def _blob_refs(rows: list[dict[str, Any]]) -> list[BlobRef]:
    """The batch as the git layer wants it, read off the rows themselves.

    Derived here rather than inside the git layer so the published name, which
    is what a question will carry, comes from the same place it was verified.
    Two code paths computing the same name is how a row ends up pointing at
    something that was never checked.
    """
    refs: list[BlobRef] = []
    for row in rows:
        digest = str(row.get("sha256") or "")
        blob_rel = str(row.get("blob_path") or "")
        extension = Path(blob_rel).suffix
        if not digest or not extension:
            continue
        refs.append((digest, extension, name_for(digest, extension)))
    return refs


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
        target = name_for(digest, extension)
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
