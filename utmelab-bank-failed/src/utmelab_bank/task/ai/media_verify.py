"""media-verify: independent calls check the description against the figure.

The description is not trusted because a model wrote it once. A separate call
sees the same bytes, the question, and the description, and returns per-claim
evidence. The row's verdict is only ``pass`` when every claim is supported and
the figure fits the question. Anything else moves the row to ``needs_review``:
the description is kept for the reviewer, but the ``description verified``
selector will not treat it as usable.

One model can share its own blind spot with itself, so a second, *different*
image model is used when configured: the description passes only when both
models pass it. A missing or disagreeing witness is a fail, never a pass. The
same model named twice is not a witness and is ignored.

A verdict is bound to the image hash and the description text. A new figure or
rewritten description invalidates it, and the description writer clears the
verdict rather than leaving a stale pass behind.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from utmelab_bank.config import Config
from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.task.ai.describe import question_context
from utmelab_bank.task.ai.media_verify_schema import MediaVerifyResult
from utmelab_bank.task.ai.media_verify_tasks import verify_media
from utmelab_bank.task.ai.providers import build_provider
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["MediaVerify", "verify_media_one", "witness_models"]

log = logging.getLogger(__name__)


@registered
class MediaVerify:
    """Check one figure description against the figure itself."""

    name = "media-verify"
    produces = "description_verdict"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Check each figure description against the figure, with evidence."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return await verify_media_one(row, ctx)

    async def collect(self, _ctx: TaskContext) -> list[RowOutcome]:
        return []


def witness_models(config: Config) -> list[str]:
    """The models that must agree before a description is usable.

    One witness is the default. A second, different image model is added when
    configured. The same model twice is not an independent check, so a duplicate
    is dropped rather than counted as a second opinion.
    """
    primary = config.ai_image_model or config.ai_model
    second = (config.ai_image_second_model or "").strip()
    models = [primary]
    if second and second != primary:
        models.append(second)
    return models


def content_hash(image_sha256: str, description: str) -> str:
    """Bind a verdict to these exact words and these exact bytes."""
    return hashlib.sha256(f"{image_sha256}\n{description}".encode()).hexdigest()


def _verification_id(row_id: str, digest: str, index: int) -> str:
    """A distinct row per witness, so two opinions do not overwrite each other."""
    base = f"v_{row_id}_{digest[:12]}"
    return base if index == 0 else f"{base}_w{index}"


async def _already_checked(ctx: TaskContext, question_id: str, digest: str, expected: int) -> bool:
    """True only when every configured witness has already recorded this digest."""
    if not question_id:
        return False
    rows = await ctx.repo.rows("verifications", f"question_id={question_id}")
    verifiers = {
        str(row.get("verifier", "")) for row in rows if str(row.get("content_hash", "")) == digest
    }
    return len(verifiers) >= expected


async def verify_media_one(row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
    """Check one media row's description and record the verdict."""
    row_id = str(row.get("id", ""))
    if not row_id:
        return ctx.skip(row_id, "no_id", "the media row has no id")

    description = str(row.get("description") or "")
    if not description:
        return ctx.skip(row_id, "no_description", "there is no description to check")

    blob_rel = str(row.get("blob_path") or "")
    if not blob_rel:
        return ctx.skip(row_id, "no_bytes", "this figure has no fetched bytes")

    image_sha256 = str(row.get("sha256") or "")
    if not image_sha256:
        return ctx.skip(row_id, "no_sha256", "this figure has no content hash")

    digest = content_hash(image_sha256, description)
    question_id = str(row.get("question_id") or "")
    models = witness_models(ctx.config)
    if await _already_checked(ctx, question_id, digest, len(models)):
        return ctx.skip(row_id, "already_checked", "this description has been checked")

    if ctx.dry_run or ctx.config.sink == "json":
        return ctx.ok(row_id)

    blob_path = ctx.config.repo.media_repo / blob_rel
    if not blob_path.is_file():
        return ctx.skip(row_id, "blob_missing", f"blob not on disk at {blob_rel}")

    stem, options = await question_context(ctx, row)
    witnesses: list[tuple[str, MediaVerifyResult]] = []
    for model in models:
        provider = build_provider(ctx.config, "opencode", model=model)
        try:
            result = await verify_media(
                provider,
                row,
                description,
                stem,
                options,
                image=str(blob_path),
            )
        finally:
            await provider.aclose()

        if result.error:
            # A witness that could not answer is not a pass. No row is written,
            # so a retry re-runs the whole check and no partial verdict is left
            # behind to look like agreement.
            return ctx.fail(row_id, "ai_failed", result.error, retryable=True)
        witnesses.append((provider.name, result))

    verdict = "pass" if all(result.verdict == "pass" for _, result in witnesses) else "fail"

    stamp = now_iso()
    await ctx.repo.insert_many(
        "verifications",
        [
            {
                "id": _verification_id(row_id, digest, index),
                "question_id": question_id or row_id,
                "kind": "ai_verify",
                "verdict": result.verdict,
                "scope": json.dumps(["media"]),
                "verifier": verifier,
                "detail": json.dumps(
                    {
                        "media_id": row_id,
                        "image_sha256": image_sha256,
                        "witness": verifier,
                        "witnesses": len(witnesses),
                        "agreement": verdict,
                        "fidelity": result.fidelity,
                        "fit": result.fit,
                        "confidence": result.confidence,
                        "claims": result.claims,
                        "reasoning": result.reasoning,
                    }
                )[:4000],
                "content_hash": digest,
                "created_at": stamp,
            }
            for index, (verifier, result) in enumerate(witnesses)
        ],
    )

    update: dict[str, Any] = {
        "description_verdict": verdict,
        "description_verified_at": stamp,
        "updated_at": stamp,
    }
    if verdict == "pass":
        update["next_retry_at"] = None
    else:
        update["status"] = "needs_review"
        # A negative verdict is data, not a task error. The runner clears the
        # error column on an ok outcome, so the durable record is the verdict,
        # the status, and the verification row's detail. A reviewer queries
        # `--where 'description failed'` and reads the claims there.
    await ctx.repo.update("media", row_id, update)

    for verifier, result in witnesses:
        log.info(
            "media-verify %s: witness=%s verdict=%s fidelity=%s fit=%s confidence=%.2f",
            row_id,
            verifier,
            result.verdict,
            result.fidelity,
            result.fit,
            result.confidence,
        )
    log.info("media-verify %s: verdict=%s witnesses=%d", row_id, verdict, len(witnesses))
    return ctx.ok(row_id)
