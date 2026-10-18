"""The one content hash, and the reason it cannot drift.

The API never recomputes this. ``src/store/catalog.rs`` builds its ``verified``
predicate by joining ``verifications.content_hash`` to ``questions.content_hash``,
so the hash we write decides whether a question counts as verified for every
candidate who ever sees it. A wrong hash is not a crash, it is a question
silently marked unverified, or worse, one marked verified that should not be.

**The part order is fixed by the bank that already exists.** The algorithm is
``Question::content_fingerprint`` from the archived Rust tree, which
``tools/review.py`` mirrored and which the pipeline's promoter claimed
byte-for-byte parity with. There are 2190 stored hashes in
``utmelab-api-old/data/verifications.json``, and this function has to produce
those same digests or every human verification ever written stops joining.

Concretely, the order is:

1. the stem text
2. one part per option, ``id`` + ``\\x1e`` + text
3. the answer
4. **every** mark, stem then options, ``|``-joined, as a single part
5. the explanation: key point text, key point marks, body text, body marks,
   trap text, trap marks. With no explanation, a single empty part. With an
   explanation but no trap, a single empty part where the trap would be.

An earlier version of this file put the stem marks in their own part and glued
each option's marks onto its own option part. That produced a different digest
for every question in the bank while looking entirely reasonable, which is the
worst way for this to be wrong. The vectors in ``tests/vectors`` are pinned from
both this implementation and the committed bank, and a mismatch is a
bank-wide event rather than a small edit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from utmelab_bank.errors import ContractError
from utmelab_bank.model.richtext import Mark, RichText, mark_key

__all__ = ["VECTORS_PATH", "check_vectors", "content_hash", "load_vectors", "stamp_rows"]

#: Unit separator between an option id and its text. Chosen because it cannot
#: appear in scraped prose, so two different splits can never collide.
_SEP: Final[str] = "\x1e"

#: Unit separator between parts.
_PART: Final[str] = "\x1f"

#: The three explanation parts, in the order the algorithm reads them.
_EXPLANATION_PARTS: Final[tuple[str, ...]] = ("key_point", "body", "trap")

VECTORS_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "tests" / "vectors" / "content_hash.json"
)


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, RichText):
        return value.text
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("text", ""))
    return str(value)


def _marks_of(value: Any) -> list[Mark]:
    """The marks on a value, tolerating the dict and list forms a row carries."""
    if isinstance(value, RichText):
        return list(value.inline)
    if isinstance(value, dict):
        raw = value.get("inline") or []
    elif isinstance(value, list):
        raw = value
    else:
        return []
    return [m if isinstance(m, Mark) else Mark.model_validate(m) for m in raw]


def _option_parts(value: Any) -> tuple[str, Any, list[Mark]]:
    """One option's id, its text value and its marks, from any of three shapes.

    The text value is returned unflattened so the caller decides how to read it,
    because an option's text is a RichText in a model and a plain string in a
    row, and getting that backwards loses every option's marks.
    """
    if isinstance(value, dict):
        return str(value.get("id", "")), value.get("text"), _marks_of(value.get("text"))
    return (
        str(getattr(value, "id", "")),
        getattr(value, "text", None),
        _marks_of(getattr(value, "text", None)),
    )


def content_hash(
    *,
    stem: RichText | dict[str, Any],
    options: list[Any],
    answer_id: str,
    explanation: Any = None,
) -> str:
    """The content hash of one question, as 64 lowercase hex characters."""
    parts: list[str] = [_text_of(stem)]

    marks: list[Mark] = list(_marks_of(stem))
    for option in options:
        option_id, option_text, option_marks = _option_parts(option)
        parts.append(f"{option_id}{_SEP}{_text_of(option_text)}")
        marks.extend(option_marks)

    parts.append(str(answer_id))
    parts.append("|".join(mark_key(mark) for mark in marks))

    if isinstance(explanation, dict) and explanation:
        for name in _EXPLANATION_PARTS:
            part = explanation.get(name)
            if not isinstance(part, dict):
                parts.append("")
                continue
            parts.append(_text_of(part))
            parts.append("|".join(mark_key(mark) for mark in _marks_of(part)))
    else:
        parts.append("")

    return hashlib.sha256(_PART.join(parts).encode("utf-8")).hexdigest()


def stamp_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stamp ``content_hash`` on question rows that do not have one.

    Called by :meth:`utmelab_bank.store.repository.Repository.insert_many` for the
    questions table, so every row that lands carries the hash the API will join
    on. A row that already has a hash is left alone: re-hashing edited content
    would silently orphan every verification written against the old text.
    """
    for row in rows:
        if row.get("content_hash"):
            continue
        row["content_hash"] = content_hash(
            stem={"text": row.get("text") or "", "inline": _load(row, "inline")},
            options=_load(row, "options"),
            answer_id=str(row.get("answer") or ""),
            explanation=_load(row, "explanation") or None,
        )
    return rows


def _load(row: dict[str, Any], column: str) -> Any:
    value = row.get(column)
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return []
    return value


def load_vectors(path: Path | None = None) -> list[dict[str, Any]]:
    """The pinned cases. Read by the Python test, and intended for a Rust one."""
    target = path or VECTORS_PATH
    if not target.is_file():
        raise ContractError("content hash vectors are missing", path=str(target))
    payload = json.loads(target.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContractError("content hash vectors have no cases", path=str(target))
    return cases


def check_vectors(cases: list[dict[str, Any]]) -> list[str]:
    """Return the names of any case whose digest has moved."""
    drifted: list[str] = []
    for case in cases:
        produced = content_hash(
            stem=case["stem"],
            options=case["options"],
            answer_id=case["answer"],
            explanation=case.get("explanation"),
        )
        if produced != case["content_hash"]:
            drifted.append(str(case.get("name", "unnamed")))
    return drifted
