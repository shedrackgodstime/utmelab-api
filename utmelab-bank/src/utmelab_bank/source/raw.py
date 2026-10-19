"""A parsed question as a raw-lane row.

Both entry points that land questions (``scrape`` and ``fill``) need the same
shape, so the builder lives here rather than in the CLI. ``payload_hash`` is
what makes a re-scrape idempotent: the raw lane's unique key is
``(source_url, source_item_id, payload_hash)``, so an unchanged page adds
nothing and an edited page appears beside the old row instead of replacing it.
"""

from __future__ import annotations

import json
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.text import rt_json

__all__ = ["raw_row", "raw_row_id"]


def raw_row_id(question_id: str, payload_hash: str) -> str:
    """A raw row's primary key: the question, plus the version we parsed."""
    return f"{question_id}#{payload_hash[:12]}"


def raw_row(item: Any, run_id: str) -> dict[str, Any]:
    """One parsed question as a raw row.

    ``payload_hash`` is what makes a re-scrape idempotent: an unchanged page
    adds nothing and an edited page appears beside the old row instead of
    replacing it. The work lane is where the two are reconciled.
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
        "passage_id": None,
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
