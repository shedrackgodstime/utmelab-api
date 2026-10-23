"""The production reference reader: read-only taxonomy and content hashes."""

from __future__ import annotations

from pathlib import Path

import pytest

from utmelab_bank.config import Config
from utmelab_bank.errors import ConfigError, StoreError
from utmelab_bank.store.client import Store
from utmelab_bank.store.reference import Reference


async def _seed_production(store: Store) -> None:
    await store.execute(
        "CREATE TABLE topics (slug TEXT PRIMARY KEY, subject TEXT, exam TEXT, "
        'name TEXT, "order" INTEGER, weight REAL, objectives TEXT)'
    )
    await store.execute(
        "CREATE TABLE subtopics (slug TEXT PRIMARY KEY, topic TEXT, name TEXT, "
        '"order" INTEGER, objectives TEXT)'
    )
    await store.execute(
        "CREATE TABLE subjects (slug TEXT PRIMARY KEY, exam TEXT, name TEXT, "
        "is_compulsory INTEGER, objective_paper_questions INTEGER)"
    )
    await store.execute("CREATE TABLE questions (id TEXT PRIMARY KEY, content_hash TEXT)")

    await store.execute(
        "INSERT INTO topics VALUES ('algebra', 'mathematics', 'JAMB', 'Algebra', 1, 1.0, "
        "'[\"Solve equations\"]')"
    )
    await store.execute(
        "INSERT INTO topics VALUES ('geometry', 'mathematics', 'JAMB', 'Geometry', 2, 1.0, '[]')"
    )
    await store.execute(
        "INSERT INTO subtopics VALUES ('linear-equations', 'algebra', 'Linear Equations', 1, '[]')"
    )
    await store.execute(
        "INSERT INTO subtopics VALUES ('angles', 'geometry', 'Angles', 1, '[]')"
    )
    await store.execute(
        "INSERT INTO subjects VALUES ('mathematics', 'JAMB', 'Mathematics', 1, 40)"
    )
    await store.execute("INSERT INTO questions VALUES ('q1', 'abc123')")


async def test_subtopics_come_back_for_the_subject_and_exam(store: Store) -> None:
    await _seed_production(store)
    reference = Reference(store)

    subtopics, topics = await reference.topics_and_subtopics("mathematics", "jamb")

    assert [s["slug"] for s in subtopics] == ["linear-equations", "angles"]
    assert [t["slug"] for t in topics] == ["algebra", "geometry"]
    assert topics[0]["objectives"] == ["Solve equations"]
    assert topics[0]["exam"] == "JAMB"


async def test_subtopics_are_cached_per_subject(store: Store) -> None:
    await _seed_production(store)
    reference = Reference(store)

    first, _ = await reference.topics_and_subtopics("mathematics", "JAMB")
    second, _ = await reference.topics_and_subtopics("mathematics", "jamb")

    assert first is second


async def test_one_subtopic_carries_its_topic_context(store: Store) -> None:
    await _seed_production(store)
    reference = Reference(store)

    subtopic = await reference.subtopic("linear-equations")

    assert subtopic is not None
    assert subtopic["subject"] == "mathematics"
    assert subtopic["exam"] == "JAMB"
    assert subtopic["topic"] == "algebra"


async def test_a_missing_subtopic_is_none(store: Store) -> None:
    await _seed_production(store)
    assert await Reference(store).subtopic("nope") is None


async def test_subject_is_readable(store: Store) -> None:
    await _seed_production(store)
    reference = Reference(store)

    subject = await reference.subject("mathematics", "jamb")

    assert subject is not None
    assert subject["name"] == "Mathematics"


async def test_content_hashes_are_loaded_once_and_answered(store: Store) -> None:
    await _seed_production(store)
    reference = Reference(store)

    assert await reference.has_content_hash("abc123") is True
    assert await reference.has_content_hash("missing") is False
    assert await reference.has_content_hash("") is False


async def test_null_objectives_read_as_empty(store: Store) -> None:
    await _seed_production(store)
    await store.execute("INSERT INTO subtopics VALUES ('bare', 'geometry', 'Bare', 2, NULL)")
    reference = Reference(store)

    subtopic = await reference.subtopic("bare")

    assert subtopic is not None
    assert subtopic["objectives"] == []


async def test_open_refuses_without_a_production_url(config: Config) -> None:
    with pytest.raises(ConfigError):
        await Reference.open(config)


async def test_a_read_only_store_refuses_writes(tmp_path: Path) -> None:
    store = await Store.open(f"sqlite:{tmp_path / 'prod.db'}", read_only=True)
    reference = Reference(store)
    try:
        with pytest.raises(StoreError):
            await store.execute("CREATE TABLE x (y TEXT)")
    finally:
        await reference.aclose()
