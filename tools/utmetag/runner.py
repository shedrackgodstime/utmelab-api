"""Concurrency orchestration over the tagging task."""

from __future__ import annotations

import asyncio
import time

from .providers.base import Provider
from .schema import QuestionInput, SubtopicInfo, TagResult, TopicInfo
from .tasks import tag_question


async def run(
    provider: Provider,
    questions: list[QuestionInput],
    subtopics: list[SubtopicInfo],
    topics: list[TopicInfo],
    concurrency: int = 3,
) -> list[TagResult]:
    """Tag every question, bounded by ``concurrency``, preserving input order."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def worker(q: QuestionInput) -> TagResult:
        async with semaphore:
            return await tag_question(provider, q, subtopics, topics)

    results = await asyncio.gather(*(worker(q) for q in questions), return_exceptions=True)

    final: list[TagResult] = []
    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            final.append(TagResult(question_id=questions[i].id, error=f"Exception: {result}"))
        else:
            final.append(result)
    return final


def summarize(results: list[TagResult], elapsed: float) -> dict:
    return {
        "total": len(results),
        "success": sum(1 for r in results if r.error is None),
        "failed": sum(1 for r in results if r.error is not None),
        "subtopics_assigned": sum(1 for r in results if r.assigned_subtopic),
        "underlines_found": sum(1 for r in results if r.underline_word),
        "answers_verified": sum(1 for r in results if r.answer_verified),
        "duration_seconds": round(elapsed, 2),
    }
