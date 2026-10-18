"""Whether a row counts as verified, and the checks verify refuses on.

Verified is derived from the verifications lane, never stored on the row:
a ``human`` row with ``verdict='pass'`` over both ``answer`` and
``explanation``, on the row's current ``content_hash``, with no later such
row. An edit changes the hash and voids every verification silently — which
is the correct behaviour, because a verdict about old content is not a
verdict about new content.
"""

from __future__ import annotations

from typing import Any

from utmelab_bank.model.base import now_iso
from utmelab_bank.rules import judge_row
from utmelab_bank.store.repository import Repository

__all__ = ["gate_flags", "is_verified", "verifications_for", "write_verification"]

#: Scopes a human pass must name for the row to read as verified.
NEEDED_SCOPE: frozenset[str] = frozenset({"answer", "explanation"})


def verifications_for(rows: list[dict[str, Any]], question_id: str) -> list[dict[str, Any]]:
    """The verification rows for one question, newest first."""
    found = [r for r in rows if str(r.get("question_id", "")) == question_id]
    found.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return found


def is_verified(verifications: list[dict[str, Any]], row: dict[str, Any]) -> bool:
    """Whether a human pass covers this row's current content."""
    digest = str(row.get("content_hash") or "")
    if not digest:
        return False
    for v in verifications_for(verifications, str(row.get("id", ""))):
        if str(v.get("content_hash") or "") != digest:
            continue
        if str(v.get("kind", "")) != "human" or str(v.get("verdict", "")) != "pass":
            continue
        scope = v.get("scope")
        if isinstance(scope, str):
            import json

            try:
                scope = json.loads(scope)
            except ValueError:
                scope = []
        if NEEDED_SCOPE.issubset(set(scope or [])):
            return True
    return False


def gate_flags(row: dict[str, Any]) -> list[str]:
    """The gate reasons that make this row unverifiable as it stands."""
    return list(judge_row(row).reasons)


async def write_verification(
    repo: Repository,
    row: dict[str, Any],
    *,
    by: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Append a human/pass row covering answer+explanation, with refusals first."""
    row_id = str(row.get("id", ""))
    verifications = await repo.rows("verifications", "all", limit=None)
    if is_verified(verifications, row):
        raise _Refusal(f"{row_id} already verified")
    flags = gate_flags(row)
    if flags:
        raise _Refusal(f"resolve first: {', '.join(flags)}")
    if not row.get("explanation"):
        raise _Refusal("verified claims the working was checked — write the explanation first")
    digest = str(row.get("content_hash") or "")
    if not digest:
        raise _Refusal("the row has no content hash")
    stamp = now_iso()
    existing = [r for r in verifications if str(r.get("question_id", "")) == row_id]
    verification: dict[str, Any] = {
        "id": f"v_{row_id}_human_{len(existing) + 1:04d}",
        "question_id": row_id,
        "kind": "human",
        "verdict": "pass",
        "scope": '["answer", "explanation"]',
        "verifier": by,
        "detail": None,
        "content_hash": digest,
        "created_at": stamp,
    }
    if not dry_run:
        await repo.insert_many("verifications", [verification])
    return verification


class _Refusal(Exception):
    """A verify/set refusal. The CLI turns these into a line, not a traceback."""
