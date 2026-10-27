"""Reseed one subject in the production WAEC catalog.

The JSON is the source of truth for names and order. Production keeps the
slug when the name has not changed, so existing snapshots keep resolving, and
keeps any subtopic a question still points at even when the rebuilt catalog no
longer lists it. A dry run is the default.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ..adapters.database import TursoClient
from .pdf import normalise

Row = tuple[Any, ...]


@dataclass(slots=True)
class Plan:
    """Everything one subject's reseed will do."""

    subject_slug: str
    subject: dict[str, Any]
    topics: list[dict[str, Any]] = field(default_factory=list)
    subtopics: list[dict[str, Any]] = field(default_factory=list)
    delete_subtopics: list[str] = field(default_factory=list)
    delete_topics: list[str] = field(default_factory=list)
    kept_referenced: list[str] = field(default_factory=list)
    kept_topics: list[str] = field(default_factory=list)
    reused_topics: int = 0
    reused_subtopics: int = 0

    def summary(self) -> str:
        return (
            f"{self.subject_slug}: {len(self.topics)} topics, "
            f"{len(self.subtopics)} subtopics; reuse {self.reused_topics} topics/"
            f"{self.reused_subtopics} subtopics; delete "
            f"{len(self.delete_topics)} topics/{len(self.delete_subtopics)} subtopics; "
            f"keep {len(self.kept_referenced)} referenced subtopics"
        )


async def _rows(client: TursoClient, sql: str, args: list[Any] | None = None) -> list[Row]:
    result = await client.execute(sql, args or [])
    return list(result.rows)


def _unique(desired: str, taken: set[str]) -> str:
    if desired and desired not in taken:
        taken.add(desired)
        return desired
    base = desired or "waec-topic"
    for suffix in range(2, 1000):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise ValueError(f"cannot find a free slug for {desired!r}")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _first_subject(data: dict[str, Any]) -> dict[str, Any]:
    subjects = data.get("subjects") or []
    return subjects[0] if subjects else {}


async def plan_subject(client: TursoClient, data: dict[str, Any], subject_slug: str) -> Plan:
    """Read the current subject and produce a plan without writing anything."""
    json_subject = _first_subject(data)
    json_topics = list(data.get("topics") or [])
    json_subtopics = list(data.get("subtopics") or [])

    old_topics = await _rows(
        client,
        'SELECT slug, name, "order", weight, objectives, countries '
        "FROM topics WHERE exam = 'WAEC' AND subject = ?",
        [subject_slug],
    )
    old_topic_slugs = [str(row[0]) for row in old_topics]
    old_subtopics: list[Row] = []
    referenced: set[str] = set()
    if old_topic_slugs:
        placeholders = ",".join("?" for _ in old_topic_slugs)
        old_subtopics = await _rows(
            client,
            'SELECT slug, topic, name, "order", objectives '
            f"FROM subtopics WHERE topic IN ({placeholders})",
            old_topic_slugs,
        )
        referenced = {
            str(row[0])
            for row in await _rows(
                client,
                f"SELECT DISTINCT s.slug FROM subtopics s "
                f"JOIN questions q ON q.subtopic_id = s.slug "
                f"WHERE s.topic IN ({placeholders})",
                old_topic_slugs,
            )
        }

    old_subject = await _rows(
        client,
        "SELECT name, is_compulsory, objective_paper_questions, countries "
        "FROM subjects WHERE slug = ? AND exam = 'WAEC'",
        [subject_slug],
    )
    all_topic_slugs = {str(row[0]) for row in await _rows(client, "SELECT slug FROM topics")}
    all_subtopic_slugs = {str(row[0]) for row in await _rows(client, "SELECT slug FROM subtopics")}

    old_by_name: dict[str, list[Row]] = defaultdict(list)
    for row in old_topics:
        old_by_name[normalise(str(row[1]))].append(row)
    old_sub_by_name: dict[tuple[str, str], list[Row]] = defaultdict(list)
    old_sub_parent: dict[str, str] = {}
    for row in old_subtopics:
        old_sub_by_name[(str(row[1]), normalise(str(row[2])))].append(row)
        old_sub_parent[str(row[0])] = str(row[1])

    used_old_topics: set[str] = set()
    used_old_subtopics: set[str] = set()
    by_json_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in json_subtopics:
        by_json_topic[str(row.get("topic") or "")].append(row)

    plan = Plan(subject_slug=subject_slug, subject=json_subject)
    for row in json_topics:
        json_slug = str(row.get("slug") or "")
        name = str(row.get("name") or "")
        match: Row | None = None
        for candidate in old_by_name.get(normalise(name), []):
            if str(candidate[0]) not in used_old_topics:
                match = candidate
                break

        if match is not None:
            final_slug = str(match[0])
            used_old_topics.add(final_slug)
            plan.reused_topics += 1
            weight = int(match[3])
            objectives = str(match[4])
            countries = str(match[5])
        else:
            final_slug = _unique(json_slug, all_topic_slugs)
            weight = int(row.get("weight") or 0)
            objectives = _json(row.get("objectives"))
            countries = _json(row.get("countries"))
        plan.topics.append(
            {
                "slug": final_slug,
                "name": name,
                "order": int(row.get("order") or len(plan.topics) + 1),
                "weight": weight,
                "objectives": objectives,
                "countries": countries,
            }
        )

        for sub in by_json_topic.get(json_slug, []):
            sub_name = str(sub.get("name") or "")
            sub_slug = str(sub.get("slug") or "")
            old_sub: Row | None = None
            if match is not None:
                for candidate in old_sub_by_name.get((str(match[0]), normalise(sub_name)), []):
                    if str(candidate[0]) not in used_old_subtopics:
                        old_sub = candidate
                        break
            if old_sub is not None:
                final_sub_slug = str(old_sub[0])
                used_old_subtopics.add(final_sub_slug)
                plan.reused_subtopics += 1
                objectives = str(old_sub[4])
            else:
                final_sub_slug = _unique(sub_slug, all_subtopic_slugs)
                objectives = _json(sub.get("objectives"))
            plan.subtopics.append(
                {
                    "slug": final_sub_slug,
                    "topic": final_slug,
                    "name": sub_name,
                    "order": int(sub.get("order") or len(plan.subtopics) + 1),
                    "objectives": objectives,
                }
            )

    new_topic_slugs = {str(row["slug"]) for row in plan.topics}
    new_sub_slugs = {str(row["slug"]) for row in plan.subtopics}
    keep_topic_slugs = set(new_topic_slugs)
    for slug in referenced:
        parent = old_sub_parent.get(slug)
        if parent:
            keep_topic_slugs.add(parent)
            plan.kept_referenced.append(slug)
            if parent not in plan.kept_topics:
                plan.kept_topics.append(parent)
    keep_sub_slugs = new_sub_slugs | referenced

    plan.delete_subtopics = [
        str(row[0]) for row in old_subtopics if str(row[0]) not in keep_sub_slugs
    ]
    plan.delete_topics = [str(row[0]) for row in old_topics if str(row[0]) not in keep_topic_slugs]

    name = str(json_subject.get("name") or "")
    if not name and old_subject:
        name = str(old_subject[0][0])
    is_compulsory = json_subject.get("is_compulsory")
    if is_compulsory is None and old_subject:
        is_compulsory = bool(old_subject[0][1])
    objective = json_subject.get("objective_paper_questions")
    if objective is None and old_subject:
        objective = old_subject[0][2]
    subject_countries = json_subject.get("countries")
    if not subject_countries and old_subject:
        subject_countries = json.loads(str(old_subject[0][3]) or "[]")
    plan.subject = {
        "slug": subject_slug,
        "name": name,
        "is_compulsory": bool(is_compulsory),
        "objective_paper_questions": int(objective or 0),
        "countries": _json(subject_countries),
        "syllabus_exam": "WAEC",
        "syllabus_subject": subject_slug,
    }
    return plan


def _chunks(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def apply_plan(client: TursoClient, plan: Plan, *, commit: bool = True) -> None:
    """Write a plan. A failure leaves production unchanged.

    ``commit=False`` keeps the plan in the open transaction so a caller can
    publish several subjects and validate the result before landing it.
    """
    for chunk in _chunks(plan.topics, 50):
        placeholders = ",".join("(?, ?, 'WAEC', ?, ?, ?, ?, ?)" for _ in chunk)
        args: list[Any] = []
        for row in chunk:
            args.extend(
                [
                    row["slug"],
                    plan.subject_slug,
                    row["name"],
                    row["order"],
                    row["weight"],
                    row["objectives"],
                    row["countries"],
                ]
            )
        await client.execute(
            'INSERT INTO topics (slug, subject, exam, name, "order", weight, objectives, countries) '
            f"VALUES {placeholders} "
            "ON CONFLICT(slug) DO UPDATE SET subject = excluded.subject, "
            "exam = excluded.exam, name = excluded.name, "
            '"order" = excluded."order", weight = excluded.weight, '
            "objectives = excluded.objectives, countries = excluded.countries",
            args,
            commit=False,
        )
    for chunk in _chunks(plan.subtopics, 100):
        placeholders = ",".join("(?, ?, ?, ?, ?)" for _ in chunk)
        args = []
        for row in chunk:
            args.extend(
                [
                    row["slug"],
                    row["topic"],
                    row["name"],
                    row["order"],
                    row["objectives"],
                ]
            )
        await client.execute(
            'INSERT INTO subtopics (slug, topic, name, "order", objectives) '
            f"VALUES {placeholders} "
            "ON CONFLICT(slug) DO UPDATE SET topic = excluded.topic, "
            'name = excluded.name, "order" = excluded."order", '
            "objectives = excluded.objectives",
            args,
            commit=False,
        )
    for chunk in _chunks(plan.delete_subtopics, 100):
        marks = ",".join("?" for _ in chunk)
        await client.execute(f"DELETE FROM subtopics WHERE slug IN ({marks})", chunk, commit=False)
    for chunk in _chunks(plan.delete_topics, 100):
        marks = ",".join("?" for _ in chunk)
        await client.execute(f"DELETE FROM topics WHERE slug IN ({marks})", chunk, commit=False)
    subject = plan.subject
    await client.execute(
        "INSERT INTO subjects (slug, exam, name, is_compulsory, objective_paper_questions, "
        "syllabus_exam, syllabus_subject, countries) "
        "VALUES (?, 'WAEC', ?, ?, ?, 'WAEC', ?, ?) "
        "ON CONFLICT(slug, exam) DO UPDATE SET name = excluded.name, "
        "is_compulsory = excluded.is_compulsory, "
        "objective_paper_questions = excluded.objective_paper_questions, "
        "syllabus_exam = excluded.syllabus_exam, "
        "syllabus_subject = excluded.syllabus_subject, countries = excluded.countries",
        [
            plan.subject_slug,
            subject["name"],
            int(bool(subject["is_compulsory"])),
            subject["objective_paper_questions"],
            subject["syllabus_subject"],
            subject["countries"],
        ],
        commit=False,
    )
    if commit:
        await client.commit()


__all__ = ["Plan", "apply_plan", "plan_subject"]
