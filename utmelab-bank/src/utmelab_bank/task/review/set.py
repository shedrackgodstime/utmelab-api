"""Scalar edits on a work row, validated before anything writes.

Every edit is checked before it lands: the subtopic must exist under the
row's exam+subject, the underline must be a substring of the stem, marks and
difficulty stay in range, the passage must exist. The row's ``content_hash``
is re-stamped after an edit, so any earlier verification no longer joins —
an edit voids the verdict, by design.
"""

from __future__ import annotations

import json
from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.store.repository import Repository
from utmelab_bank.task.review.verify import _Refusal

__all__ = ["set_fields"]


async def set_fields(
    repo: Repository,
    row: dict[str, Any],
    *,
    subtopic: str | None = None,
    underline: str | None = None,
    section: str | None = None,
    marks: float | None = None,
    difficulty: int | None = None,
    passage: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply scalar edits to one work row. Returns the fields that changed."""
    row_id = str(row.get("id", ""))
    changed: dict[str, Any] = {}

    if subtopic is not None:
        await _require_subtopic(repo, row, subtopic)
        changed["subtopic_id"] = subtopic

    if underline is not None:
        changed_text, changed_inline = _underline_edit(
            str(row.get("text") or ""), _loads(row.get("inline"), []), underline
        )
        changed["text"] = changed_text
        changed["inline"] = json.dumps(changed_inline)
        # An edit changes the content; re-stamp so old verifications stop joining.
        changed["content_hash"] = ""

    if section is not None:
        changed["section"] = section

    if marks is not None:
        if not 0.0 <= marks <= 100.0:
            raise _Refusal("marks look wrong - JAMB rows carry 1.0-3.0")
        changed["marks"] = marks

    if difficulty is not None:
        if difficulty not in (1, 2, 3, 4, 5):
            raise _Refusal("difficulty is 1-5")
        changed["difficulty"] = difficulty

    if passage is not None:
        await _require_passage(repo, passage)
        changed["passage_id"] = passage

    if changed and not dry_run:
        from utmelab_bank.contract.content_hash import stamp_rows

        changed["updated_at"] = now_iso()
        staged = [{**row, **changed}]
        stamp_rows(staged)
        changed.update(
            {
                key: staged[0].get(key)
                for key in ("text", "inline", "content_hash")
                if key in changed
            }
        )
        await repo.update("questions", row_id, changed)

    return changed


def _loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return value


def _underline_edit(stem: str, inline: list[Any], phrase: str) -> tuple[str, list[Any]]:
    """Replace any existing underline with one mark over ``phrase``."""
    if not phrase or phrase not in stem:
        raise _Refusal("underline must be a non-empty substring of the stem")
    start = stem.find(phrase)
    kept = [m for m in inline if not (isinstance(m, dict) and m.get("kind") == "underline")]
    kept.append({"kind": "underline", "start": start, "len": len(phrase)})
    kept.sort(key=lambda m: (m.get("start", 0), m.get("len", 0)) if isinstance(m, dict) else (0, 0))
    return (stem, kept)


async def _require_subtopic(repo: Repository, row: dict[str, Any], slug: str) -> None:
    subtopics = await repo.rows("subtopics", "all", limit=None)
    topics = await repo.rows("topics", "all", limit=None)
    found = next((s for s in subtopics if str(s.get("slug", "")) == slug), None)
    if found is None:
        raise _Refusal(f"no subtopic {slug!r} — tag what exists")
    exam, subject = str(row.get("exam", "")), str(row.get("subject", ""))
    topic_slug = str(found.get("topic", ""))
    if not any(
        str(t.get("slug", "")) == topic_slug
        and str(t.get("exam", "")) == exam
        and str(t.get("subject", "")) == subject
        for t in topics
    ):
        raise _Refusal(f"no subtopic {slug!r} under {exam}/{subject} — tag what exists")


async def _require_passage(repo: Repository, passage_id: str) -> None:
    rows = await repo.rows("passages", "all", limit=None)
    if passage_id not in {str(r.get("id", "")) for r in rows}:
        raise _Refusal(f"no passage {passage_id!r}")
