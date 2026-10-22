"""Contract tests for the production catalog reader."""

import json
from typing import Any

import pytest

from utmelab_bank.adapters.catalog import ProductionCatalogReader


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows


class FakeClient:
    """A stand-in for the Turso client that answers the catalog queries."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Any] | None]] = []

    async def execute(self, statement: str, args: list[Any] | None = None) -> Any:
        self.calls.append((statement, args))
        if "FROM subjects" in statement:
            if args and args[1] != "biology":
                return FakeResult([])
            return FakeResult([("biology", "JAMB", "Biology")])
        if "FROM topics" in statement:
            return FakeResult(
                [
                    ("living-organisms", "Living Organisms", json.dumps(["Identify cells"])),
                    ("evolution-among-organisms", "Evolution", json.dumps([])),
                ]
            )
        if "FROM subtopics" in statement:
            return FakeResult(
                [
                    (
                        "cell-structure",
                        "living-organisms",
                        "Cell structure",
                        json.dumps(["Name the organelles"]),
                    ),
                ]
            )
        return FakeResult([])


async def test_snapshot_reads_subject_topics_and_subtopics() -> None:
    reader = ProductionCatalogReader(FakeClient())
    snapshot = await reader.snapshot("JAMB", "biology")

    assert snapshot.exam == "JAMB"
    assert snapshot.subject == "biology"
    assert len(snapshot.topics) == 2
    assert len(snapshot.subtopics) == 1
    assert snapshot.topics[0].objectives == ("Identify cells",)
    assert snapshot.subtopics[0].topic_id == "living-organisms"
    assert snapshot.subtopics[0].objectives == ("Name the organelles",)


async def test_snapshot_version_is_stable_and_content_addressed() -> None:
    reader = ProductionCatalogReader(FakeClient())
    first = await reader.snapshot("JAMB", "biology")
    second = await reader.snapshot("JAMB", "biology")

    assert first.version == second.version
    assert first.version.startswith("sha256:")


async def test_snapshot_refuses_an_unknown_subject() -> None:
    reader = ProductionCatalogReader(FakeClient())
    with pytest.raises(LookupError, match="no subject"):
        await reader.snapshot("JAMB", "not-a-subject")
