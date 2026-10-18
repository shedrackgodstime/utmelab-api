"""ai-explain: ask the model to write a key_point / body / trap explanation."""

from __future__ import annotations

import json
import logging
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.task.ai.explain_tasks import explain_question
from utmelab_bank.task.ai.providers import build_provider
from utmelab_bank.task.base import TaskContext, registered

__all__ = ["AiExplain", "explain_one"]

log = logging.getLogger(__name__)


@registered
class AiExplain:
    """Ask the model to write a key_point / body / trap explanation."""

    name = "ai-explain"
    produces = "explanation"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    description = "Ask the model to write a key_point / body / trap explanation."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return await explain_one(row, ctx)

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


def _rt(text: str) -> dict[str, Any]:
    return {"text": text, "inline": []}


async def explain_one(row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
    """Explain one work row: stamp the explanation + insert a verification."""
    row_id = str(row.get("id", ""))
    if not row_id:
        return ctx.skip(row_id, "no_id", "the row has no id")

    if row.get("explanation"):
        return ctx.skip(row_id, "already_explained", "this row already has an explanation")

    if ctx.dry_run or ctx.config.sink == "json":
        return ctx.ok(row_id)

    stem = str(row.get("text") or "")
    options_raw = _loads(row.get("options"), [])
    option_texts: list[str] = []
    for entry in options_raw:
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        text = str(body.get("text", "")) if isinstance(body, dict) else str(body or "")
        option_texts.append(text)
    answer = str(row.get("answer", ""))

    provider = build_provider(ctx.config, "opencode")
    try:
        result = await explain_question(provider, row_id, stem, option_texts, answer)
    finally:
        await provider.aclose()

    if result.error:
        return ctx.fail(row_id, "ai_failed", result.error, retryable=True)
    if not result.body:
        return ctx.skip(row_id, "empty_explanation", "the model returned no usable explanation")

    explanation = {
        "key_point": _rt(result.key_point),
        "body": _rt(result.body),
        "trap": _rt(result.trap),
    }

    await ctx.repo.update(
        "questions",
        row_id,
        {
            "explanation": json.dumps(explanation),
            "updated_at": now_iso(),
        },
    )

    content_hash = str(row.get("content_hash") or "")
    await ctx.repo.insert_many(
        "verifications",
        [
            {
                "id": f"v_{row_id}_explain",
                "question_id": row_id,
                "kind": "ai_explain",
                "verdict": "pass",
                "scope": json.dumps(["answer", "explanation"]),
                "verifier": provider.name,
                "detail": None,
                "content_hash": content_hash,
                "created_at": now_iso(),
            }
        ],
    )

    log.info("ai-explain %s: body=%d chars", row_id, len(result.body))
    return ctx.ok(row_id)
