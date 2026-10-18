"""ai-verify: ask the model for a pass/fail verdict on a tagged, explained row."""

from __future__ import annotations

import json
import logging
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.task.ai.providers import build_provider
from utmelab_bank.task.ai.verify_tasks import verify_question
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["AiVerify", "verify_one"]

log = logging.getLogger(__name__)


@registered
class AiVerify:
    """Ask the model for a pass/fail verdict on a tagged, explained row."""

    name = "ai-verify"
    produces = "verdict"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Ask the model for a pass/fail verdict on a tagged, explained row."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return await verify_one(row, ctx)

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


def _texts(options_raw: Any) -> list[str]:
    texts: list[str] = []
    for entry in options_raw:
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        text = str(body.get("text", "")) if isinstance(body, dict) else str(body or "")
        texts.append(f"{entry.get('id', '')}) {text}".strip())
    return texts


async def _already_judged(ctx: TaskContext, row_id: str, content_hash: str) -> bool:
    """Whether an ai_verify verdict already covers this row's content."""
    rows = await ctx.repo.rows("verifications", f"question_id={row_id}")
    return any(
        str(r.get("kind", "")) == "ai_verify" and str(r.get("content_hash", "")) == content_hash
        for r in rows
    )


async def verify_one(row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
    """Verify one work row and record the model's verdict."""
    row_id = str(row.get("id", ""))
    if not row_id:
        return ctx.skip(row_id, "no_id", "the row has no id")

    if not row.get("subtopic_id") or not row.get("explanation"):
        return ctx.skip(row_id, "not_tagged", "verify needs a subtopic and an explanation")

    content_hash = str(row.get("content_hash") or "")
    if not content_hash:
        return ctx.skip(row_id, "no_content_hash", "the row has no content hash")

    if await _already_judged(ctx, row_id, content_hash):
        return ctx.skip(row_id, "already_judged", "an ai_verify verdict covers this content")

    if ctx.dry_run or ctx.config.sink == "json":
        return ctx.ok(row_id)

    stem = str(row.get("text") or "")
    answer = str(row.get("answer", ""))
    subtopic = str(row.get("subtopic_id") or "")
    explanation = _loads(row.get("explanation"), {})
    key_point = str(
        explanation.get("key_point", {}).get("text", "")
        if isinstance(explanation.get("key_point"), dict)
        else explanation.get("key_point", "")
    )
    body = str(
        explanation.get("body", {}).get("text", "")
        if isinstance(explanation.get("body"), dict)
        else explanation.get("body", "")
    )
    trap = str(
        explanation.get("trap", {}).get("text", "")
        if isinstance(explanation.get("trap"), dict)
        else explanation.get("trap", "")
    )

    provider = build_provider(ctx.config, "opencode")
    try:
        result = await verify_question(
            provider,
            row_id,
            stem,
            _texts(_loads(row.get("options"), [])),
            answer,
            key_point,
            body,
            trap,
            subtopic,
        )
    finally:
        await provider.aclose()

    if result.error:
        return ctx.fail(row_id, "ai_failed", result.error, retryable=True)

    await ctx.repo.insert_many(
        "verifications",
        [
            {
                "id": f"v_{row_id}_verify",
                "question_id": row_id,
                "kind": "ai_verify",
                "verdict": result.verdict,
                "scope": json.dumps(result.scope or ["answer", "explanation"]),
                "verifier": provider.name,
                "detail": result.reasoning[:900] if result.reasoning else None,
                "content_hash": content_hash,
                "created_at": now_iso(),
            }
        ],
    )

    log.info("ai-verify %s: verdict=%s confidence=%.2f", row_id, result.verdict, result.confidence)
    return ctx.ok(row_id)
