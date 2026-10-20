"""ai-tag: ask the model for a subtopic, an underline, and an answer check."""

from __future__ import annotations

import json
import logging
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.task.ai.providers import build_provider
from utmelab_bank.task.ai.tasks import tag_question
from utmelab_bank.task.base import TaskContext, registered
from utmelab_bank.task.passage import passage_for, passage_text

__all__ = ["AiTag", "question_from_row", "tag_one"]

log = logging.getLogger(__name__)


@registered
class AiTag:
    """Ask the model for the subtopic, the underline, and an answer check."""

    name = "ai-tag"
    produces = "subtopic_id"
    requires: tuple[str, ...] = ()
    may_write_ready = False
    iterates_rows = True
    needs_reference = True
    description = "Ask the model for the subtopic, the underline, and an answer check."

    async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
        return await tag_one(row, ctx)

    async def collect(self, _ctx: TaskContext) -> list[RowOutcome]:
        return []


def question_from_row(
    row: dict[str, Any], passage: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The prompt-shaped question for one work-lane row."""
    text = str(row.get("text") or "")
    inline = _loads(row.get("inline"), [])
    options_raw = _loads(row.get("options"), [])
    options: list[dict[str, Any]] = []
    for entry in options_raw:
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        if isinstance(body, dict):
            options.append({"id": str(entry.get("id", "")), "text": body})
        else:
            options.append(
                {"id": str(entry.get("id", "")), "text": {"text": str(body or ""), "inline": []}}
            )
    raw = row.get("explanation")
    explanation = json.loads(raw) if isinstance(raw, str) and raw else None
    return {
        "id": str(row.get("id", "")),
        "exam": str(row.get("exam", "")),
        "subject": str(row.get("subject", "")),
        "year": row.get("year"),
        "source": str(row.get("source", "")),
        "text": {"text": text, "inline": inline if isinstance(inline, list) else []},
        "options": options,
        "answer": str(row.get("answer", "")),
        "explanation": explanation,
        "passage": passage_text(passage),
    }


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return value


async def _catalog_for(
    ctx: TaskContext, subject: str, exam: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The subject's subtopics and topics from production, prompt-shaped."""
    if ctx.reference is None:
        return [], []
    return await ctx.reference.topics_and_subtopics(subject, exam)


async def tag_one(row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
    """Tag one work row: subtopic stamped, answer check logged, failures retried."""
    row_id = str(row.get("id", ""))
    if not row_id:
        return ctx.skip(row_id, "no_id", "the row has no id")

    if row.get("subtopic_id"):
        return ctx.skip(row_id, "already_tagged", "this row already has a subtopic")

    if ctx.dry_run or ctx.config.sink == "json":
        return ctx.ok(row_id)

    subject = str(row.get("subject", ""))
    exam = str(row.get("exam", ""))
    subtopics, topics = await _catalog_for(ctx, subject, exam)
    if not subtopics:
        return ctx.skip(row_id, "no_subtopics", f"no subtopics for {subject} {exam}")

    question = question_from_row(row, await passage_for(ctx.repo, row))
    provider = build_provider(ctx.config, "opencode")
    try:
        result = await tag_question(provider, question, subtopics, topics)
    finally:
        await provider.aclose()

    if result.error:
        return ctx.fail(row_id, "ai_failed", result.error, retryable=True)

    if result.assigned_subtopic and not ctx.dry_run:
        await ctx.repo.update(
            "questions",
            row_id,
            {"subtopic_id": result.assigned_subtopic, "updated_at": now_iso()},
        )

    log.info(
        "ai-tag %s: subtopic=%s answer_ok=%s confidence=%.2f",
        row_id,
        result.assigned_subtopic,
        result.answer_verified,
        result.confidence,
    )
    return ctx.ok(row_id)
