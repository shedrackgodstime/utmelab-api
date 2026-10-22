"""Shared test helpers (no third-party async plugin required)."""

from __future__ import annotations

import asyncio
from typing import Any, Optional


def run(coro):
    """Drive an async coroutine from a plain sync test."""
    return asyncio.run(coro)


class FakeProvider:
    """A Provider whose replies (strings) or exceptions are scripted per call."""

    def __init__(self, replies: list[Any], name: str = "fake"):
        self.replies = list(replies)
        self.name = name
        self.calls: list[str] = []
        self.closed = False

    async def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.replies:
            raise AssertionError("FakeProvider ran out of scripted replies")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    async def aclose(self) -> None:
        self.closed = True


def make_question(
    qid: str,
    *,
    subject: str = "mathematics",
    exam: str = "JAMB",
    stem: str = "What is 1+1?",
    explanation: Optional[dict] = None,
    answer: str = "A",
) -> dict:
    return {
        "id": qid,
        "exam": exam,
        "subject": subject,
        "year": 2025,
        "source": "test",
        "text": {"text": stem, "inline": []},
        "options": [{"id": "A", "text": {"text": "1", "inline": []}}],
        "answer": answer,
        "subtopic_id": None,
        "explanation": explanation,
        "marks": 2.5,
        "difficulty": 3,
    }


def make_bank() -> dict:
    return {
        "subjects": [{"slug": "mathematics", "exam": "JAMB", "name": "Mathematics"}],
        "topics": [
            {"slug": "algebra", "name": "Algebra", "subject": "mathematics", "exam": "JAMB", "objectives": []},
        ],
        "subtopics": [
            {"slug": "surds", "topic": "algebra", "name": "Surds", "objectives": []},
            {"slug": "indices", "topic": "algebra", "name": "Indices", "objectives": []},
        ],
        "questions": [
            make_question("q1"),
            make_question("q2"),
            make_question("q3", subject="physics"),
            make_question("q4", exam="WAEC"),
            make_question("q5", stem="Choose the underlined word: the quick brown fox"),
        ],
        "passages": [],
        "verifications": [
            {"question_id": "q2", "kind": "human", "scope": ["answer", "explanation"], "verdict": "pass"},
        ],
    }
