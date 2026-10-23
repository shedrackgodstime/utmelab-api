"""A parsed question as a raw-lane row.

Both entry points that land questions (``scrape`` and ``fill``) need the same
shape, so the builders live here rather than in the CLI. ``payload_hash`` is
what makes a re-scrape idempotent: the raw lane's unique key is
``(source_url, source_item_id, payload_hash)``, so an unchanged page adds
nothing and an edited page appears beside the old row instead of replacing it.

A stimulus travels with the question rather than being dropped. That is the
link the gate needs and the row the work lane copies into ``passages``, so a
comprehension question is answerable rather than refused for a passage the
parser held all along.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.text import rt_json

__all__ = ["passage_id_for", "raw_passage_row", "raw_row", "raw_row_id"]


def raw_row_id(question_id: str, payload_hash: str) -> str:
    """A raw row's primary key: the question, plus the version we parsed."""
    return f"{question_id}#{payload_hash[:12]}"


def passage_kind(text: str) -> str:
    """A table or list is data; everything else is comprehension.

    The classifier is the recovery tool's, kept in step so a passage the bank
    derives is the same row production already holds.
    """
    return "Data" if "information below" in text.lower() else "Comprehension"


def passage_id_for(exam: str, subject: str, year: int | None, text: str) -> str:
    """The production passage id for one stimulus.

    Deterministic, so the same stimulus gets one id however many questions carry
    it and however many times a page is scraped. The shape mirrors the recovery
    tool's, so a bank-derived passage is the row production already has rather
    than a second copy under a different key.
    """
    digest = hashlib.sha256(text.encode()).hexdigest()[:8]
    subject_key = subject.replace("-", "_")
    return f"psg_{exam.lower()}_{year}_{subject_key}_{passage_kind(text).lower()}_{digest}"


def raw_row(item: Any, run_id: str) -> dict[str, Any]:
    """One parsed question as a raw row.

    ``payload_hash`` is what makes a re-scrape idempotent: an unchanged page
    adds nothing and an edited page appears beside the old row instead of
    replacing it. The work lane is where the two are reconciled.

    ``passage_id`` points at the row :func:`raw_passage_row` writes, when the
    page carried a stimulus. The gate reads it, and intake copies the passage
    from the raw lane into the work lane unchanged.
    """
    question = item.question
    stamp = now_iso()
    return {
        # The raw lane's identity is the question plus the payload we parsed from
        # it. Without the hash in the id, a question the site edited later would
        # collide with the version we already hold and be dropped, which is how
        # upstream drift stays invisible.
        "id": raw_row_id(question.id, item.payload_hash),
        "source_url": item.source_url,
        "source_item_id": item.source_item_id,
        "payload_hash": item.payload_hash,
        "exam": question.exam,
        "subject": question.subject,
        "year": question.year,
        "source": question.source,
        "text": question.text.text,
        "inline": rt_json(question.text.inline),
        "options": json.dumps(
            [o.model_dump(mode="json") for o in question.options], separators=(",", ":")
        ),
        "answer": question.answer,
        "subtopic_id": None,
        "section": None,
        "passage_id": _passage_id(item),
        "explanation": None,
        "marks": question.marks,
        "difficulty": question.difficulty,
        "content_hash": question.content_hash,
        "fingerprint": None,
        "gate_status": "pending",
        "gate_reason": None,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": run_id,
        "created_at": stamp,
        "updated_at": stamp,
    }


def raw_passage_row(item: Any) -> dict[str, Any] | None:
    """The raw-lane passage the question points at, or ``None``.

    One row per distinct stimulus. The id is derived from the text, so two
    questions that share a passage name the same row and a re-scrape rewrites
    nothing.
    """
    text = getattr(item, "passage", None)
    if not text:
        return None
    question = item.question
    stamp = now_iso()
    return {
        "id": _passage_id(item),
        "exam": question.exam,
        "subject": question.subject,
        "year": question.year,
        "kind": passage_kind(str(text)),
        "title": None,
        "author": None,
        "text": str(text),
        "inline": "[]",
        "created_at": stamp,
        "updated_at": stamp,
    }


def _passage_id(item: Any) -> str | None:
    """The passage id for a parsed item, or ``None`` when it carries none."""
    text = getattr(item, "passage", None)
    if not text:
        return None
    question = item.question
    return passage_id_for(question.exam, question.subject, question.year, str(text))
