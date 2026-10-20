"""One question with everything a reviewer needs, as text or as JSON."""

from __future__ import annotations

import json
from typing import Any

from utmelab_bank.store.reference import ReferenceReader
from utmelab_bank.store.repository import Repository
from utmelab_bank.task.passage import passage_for
from utmelab_bank.task.review.verify import gate_flags, is_verified, verifications_for

__all__ = ["bundle", "next_id", "render_human"]


async def bundle(repo: Repository, reference: ReferenceReader, row_id: str) -> dict[str, Any]:
    """Everything a reviewer needs for one question."""
    rows = await repo.rows("questions", f"id={row_id}")
    if not rows:
        raise _Missing(row_id)
    row = rows[0]
    verifications = [
        v
        for v in await repo.rows("verifications", "all", limit=None)
        if str(v.get("question_id", "")) == row_id
    ]
    subtopics, topics = await reference.topics_and_subtopics(
        str(row.get("subject", "")), str(row.get("exam", ""))
    )
    media = [
        m
        for m in await repo.rows("media", "all", limit=None)
        if str(m.get("question_id", "")) == row_id
    ]

    passage = await passage_for(repo, row)
    flags = gate_flags(row)
    if row.get("passage_id") and passage is None:
        flags.append("passage_missing")
    subject = await reference.subject(str(row.get("subject", "")), str(row.get("exam", "")))
    return {
        "question": row,
        "verified": is_verified(verifications, row),
        "subject": subject,
        "topic_chain": _chain(row, topics, subtopics),
        "passage": passage,
        "flags": flags,
        "verifications": verifications_for(verifications, row_id),
        "media": media,
        "siblings": [
            {"id": str(s.get("id", "")), "text": str(s.get("text", ""))[:120]}
            for s in await _siblings(repo, row)
        ],
    }


async def next_id(repo: Repository, *, subject: str | None = None) -> str:
    """The lowest-id unverified row in scope. Deterministic, no cursor."""
    rows = await repo.rows("questions", "subject=" + subject if subject else "all")
    verifications = await repo.rows("verifications", "all", limit=None)
    candidates = sorted(
        (r for r in rows if not is_verified(verifications, r)),
        key=lambda r: str(r.get("id", "")),
    )
    if not candidates:
        raise _Empty(subject)
    return str(candidates[0].get("id", ""))


def render_human(b: dict[str, Any]) -> str:
    """One question with everything related, for a terminal."""
    q = b["question"]
    lines: list[str] = []
    lines.append(
        f"{q['id']}  [{q['exam']}/{q['subject']}]  {'verified' if b['verified'] else 'unverified'}"
    )
    lines.append(
        f"source={q.get('source')} year={q.get('year')} marks={q.get('marks')} difficulty={q.get('difficulty')}"
    )
    if b["subject"]:
        lines.append(
            f"subject: {b['subject'].get('name')} ({b['subject'].get('exam')}/{b['subject'].get('slug')})"
        )
    lines.append("")
    lines.append(str(q.get("text") or ""))
    for option in _options(q):
        lines.append(f"  {option['id']}) {option['text']}")
    lines.append(f"answer: {q.get('answer')}")
    explanation = _loads(q.get("explanation"))
    if explanation:
        lines.append(
            f"key point: {_rt(explanation.get('key_point'))}\nbody:\n{_rt(explanation.get('body'))}"
        )
        if explanation.get("trap"):
            lines.append(f"trap: {_rt(explanation.get('trap'))}")
    else:
        lines.append("explanation: - none -")
    for node in b["topic_chain"]:
        lines.append(f"{node['level']}: {node['slug']} — {node['name']}")
    if b["passage"]:
        lines.append(
            f"--- passage {b['passage']['id']} ---\n{str(b['passage'].get('text') or '')}\n--- end ---"
        )
    for v in b["verifications"]:
        detail = str(v.get("detail") or "")
        lines.append(
            f"verdict {v.get('kind')}/{v.get('verdict')} on {v.get('created_at')}: {detail}".rstrip()
        )
    if b["flags"]:
        lines.append(f"FLAGS (verify refuses): {', '.join(b['flags'])}")
    if b["siblings"]:
        lines.append("siblings:")
        for s in b["siblings"]:
            lines.append(f"  {s['id']} {s['text']}")
    return "\n".join(lines) + "\n"


def _chain(
    row: dict[str, Any], topics: list[dict[str, Any]], subtopics: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    subtopic = next(
        (s for s in subtopics if str(s.get("slug", "")) == str(row.get("subtopic_id") or "")), None
    )
    if subtopic is not None:
        topic = next(
            (t for t in topics if str(t.get("slug", "")) == str(subtopic.get("topic", ""))), None
        )
        if topic is not None:
            chain.append({"level": "topic", "slug": topic["slug"], "name": topic["name"]})
        chain.append({"level": "subtopic", "slug": subtopic["slug"], "name": subtopic["name"]})
    return chain


async def _siblings(repo: Repository, row: dict[str, Any]) -> list[dict[str, Any]]:
    from utmelab_bank.store.fingerprint import normalise_for_compare

    rows = await repo.rows("questions", "all")
    stem = normalise_for_compare(str(row.get("text") or ""))
    shaped = [
        r
        for r in rows
        if str(r.get("id", "")) != str(row.get("id", ""))
        and normalise_for_compare(str(r.get("text") or "")) == stem
    ]
    return shaped[:8]


def _options(q: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in _loads(q.get("options")) or []:
        if not isinstance(entry, dict):
            continue
        body = entry.get("text")
        text = str(body.get("text", "")) if isinstance(body, dict) else str(body or "")
        out.append({"id": str(entry.get("id", "")), "text": text})
    return out


def _rt(part: Any) -> str:
    if isinstance(part, dict):
        return str(part.get("text", ""))
    return str(part or "")


def _loads(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


class _Missing(Exception):
    def __init__(self, row_id: str) -> None:
        super().__init__(f"no question {row_id!r}")


class _Empty(Exception):
    def __init__(self, subject: str | None) -> None:
        super().__init__(f"no unverified questions{' for ' + subject if subject else ''}")
