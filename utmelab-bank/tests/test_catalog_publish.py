"""The publish gate: contract first, one transaction, checked before commit."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from utmelab_bank.catalog.apply import Plan, apply_plan
from utmelab_bank.catalog.cli import _apply, _publish_defects, _validate_catalog


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows


class CountClient:
    """Answers the gate's count queries from a dictionary."""

    def __init__(self, **counts: int) -> None:
        self.counts = counts
        self.calls: list[tuple[str, list[Any] | None]] = []

    async def execute(self, sql: str, args: list[Any] | None = None) -> FakeResult:
        self.calls.append((sql, args))
        if "NOT EXISTS" in sql:
            return FakeResult([(self.counts.get("orphans", 0),)])
        if "FROM topics WHERE name IS NULL" in sql:
            return FakeResult([(self.counts.get("blank_topics", 0),)])
        if "FROM subtopics WHERE name IS NULL" in sql:
            return FakeResult([(self.counts.get("blank_subtopics", 0),)])
        if "JOIN topics t ON t.slug = s.topic" in sql:
            return FakeResult([(self.counts.get("subtopics", 0),)])
        if "FROM topics WHERE exam = 'WAEC' AND subject = ?" in sql:
            return FakeResult([(self.counts.get("topics", 0),)])
        return FakeResult([])


class WriteClient:
    """Records writes and counts commits."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits = 0

    async def execute(
        self, statement: str, args: list[Any] | None = None, *, commit: bool | None = None
    ) -> FakeResult:
        self.statements.append(statement)
        return FakeResult([])

    async def commit(self) -> None:
        self.commits += 1


def _plan(topics: int = 2, subtopics: int = 3) -> Plan:
    return Plan(
        subject_slug="geography",
        subject={
            "name": "Geography",
            "is_compulsory": False,
            "objective_paper_questions": 50,
            "syllabus_subject": "geography",
            "countries": "[]",
        },
        topics=[
            {
                "slug": f"t{i}",
                "name": f"Topic {i}",
                "order": i,
                "weight": 0,
                "objectives": "[]",
                "countries": "[]",
            }
            for i in range(1, topics + 1)
        ],
        subtopics=[
            {
                "slug": f"s{i}",
                "topic": "t1",
                "name": f"Subtopic {i}",
                "order": i,
                "objectives": "[]",
            }
            for i in range(1, subtopics + 1)
        ],
    )


def _write_subject(directory: Path, slug: str, topic_name: str) -> None:
    path = directory / f"{slug}.json"
    path.write_text(
        json.dumps(
            {
                "subjects": [{"slug": slug, "name": slug.title()}],
                "topics": [
                    {
                        "slug": "waec-topic",
                        "subject": slug,
                        "exam": "WAEC",
                        "name": topic_name,
                        "order": 1,
                    }
                ],
                "subtopics": [
                    {
                        "slug": "waec-sub",
                        "topic": "waec-topic",
                        "name": "A valid subtopic",
                        "order": 1,
                    }
                ],
            }
        )
    )


def test_a_clean_file_has_no_errors(tmp_path: Path) -> None:
    _write_subject(tmp_path, "geography", "Trade")

    result = _validate_catalog(tmp_path, ["geography"])

    assert result.errors == []
    assert result.topics == 1
    assert result.subtopics == 1


def test_a_prose_name_is_a_contract_error(tmp_path: Path) -> None:
    _write_subject(tmp_path, "geography", "X" * 310)

    result = _validate_catalog(tmp_path, ["geography"])

    assert any("too_long" in error for error in result.errors)


def test_publish_refuses_a_dirty_contract_before_it_connects(tmp_path: Path) -> None:
    _write_subject(tmp_path, "geography", "X" * 310)
    args = argparse.Namespace(data_dir=tmp_path, subject=None, apply=True, limit=5)

    assert asyncio.run(_apply(args)) == 1


def test_the_gate_accepts_the_planned_counts() -> None:
    plan = _plan()
    client = CountClient(topics=2, subtopics=3)

    assert asyncio.run(_publish_defects(client, [plan])) == []


def test_the_gate_rejects_a_missing_topic() -> None:
    plan = _plan()
    client = CountClient(topics=1, subtopics=3)

    defects = asyncio.run(_publish_defects(client, [plan]))

    assert any("topics after write" in defect for defect in defects)


def test_the_gate_rejects_a_blank_name() -> None:
    plan = _plan()
    client = CountClient(topics=2, subtopics=3, blank_topics=1)

    defects = asyncio.run(_publish_defects(client, [plan]))

    assert any("blank topic" in defect for defect in defects)


def test_apply_keeps_the_transaction_open_until_the_caller_commits() -> None:
    plan = _plan()
    client = WriteClient()

    asyncio.run(apply_plan(client, plan, commit=False))

    assert client.statements
    assert client.commits == 0

    asyncio.run(apply_plan(client, plan, commit=True))

    assert client.commits == 1
