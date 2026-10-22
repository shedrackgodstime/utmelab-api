"""The passage as its own object, in the production shape."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from utmelab_bank.adapters.sources.fixture import FixtureSource
from utmelab_bank.domain.enums import PassageKind
from utmelab_bank.domain.models import (
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Content,
    Option,
    Passage,
    RichText,
    Scope,
    SourceItem,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sources" / "fixture"


def make_passage(**overrides: object) -> Passage:
    data: dict[str, object] = {
        "id": "psg_1",
        "exam": "JAMB",
        "subject": "use-of-english",
        "year": 2025,
        "kind": PassageKind.COMPREHENSION,
        "title": "Passage A",
        "author": None,
        "text": RichText(text="Adura had learned to read the room."),
    }
    data.update(overrides)
    return Passage.model_validate(data)


def make_content(**overrides: object) -> Content:
    data: dict[str, object] = {
        "stem": RichText(text="What did Adura learn first?"),
        "options": (
            Option(id="a", text=RichText(text="to read the room")),
            Option(id="b", text=RichText(text="to read words")),
            Option(id="c", text=RichText(text="to count")),
            Option(id="d", text=RichText(text="to sing")),
        ),
        "answer": "a",
        "marks": 1.0,
    }
    data.update(overrides)
    return Content.model_validate(data)


# ── the shape ───────────────────────────────────────────────────────────────


def test_a_passage_carries_the_production_columns() -> None:
    passage = make_passage()

    assert passage.id == "psg_1"
    assert passage.exam == "JAMB"
    assert passage.subject == "use-of-english"
    assert passage.year == 2025
    assert passage.kind is PassageKind.COMPREHENSION
    assert passage.title == "Passage A"
    assert passage.author is None
    assert passage.text.text.startswith("Adura")


def test_a_passage_needs_a_kind() -> None:
    with pytest.raises(ValidationError):
        make_passage(kind="Story")


def test_the_four_kinds_are_the_production_ones() -> None:
    assert [kind.value for kind in PassageKind] == [
        "Comprehension",
        "Cloze",
        "ReadingText",
        "Data",
    ]


def test_a_question_names_a_passage_by_id() -> None:
    """A reference, not the passage itself, so two questions can share one."""
    content = make_content(passage_id="psg_1")

    assert content.passage_id == "psg_1"


def test_two_questions_can_share_one_passage() -> None:
    first = make_content(passage_id="psg_1")
    second = make_content(passage_id="psg_1")

    assert first.passage_id == second.passage_id


# ── the fixture source builds the production shape ──────────────────────────


def test_the_fixture_source_builds_a_passage() -> None:
    payload = {
        "source_item_id": "eng-2025-001",
        "source_url": "https://fixture.example/items/eng-2025-001",
        "scope": {"exam": "JAMB", "subject": "use-of-english", "year": 2025},
        "payload": {
            "stem": "What did Adura learn first?",
            "options": [
                {"id": "a", "text": "to read the room"},
                {"id": "b", "text": "to read words"},
                {"id": "c", "text": "to count"},
                {"id": "d", "text": "to sing"},
            ],
            "answer": "a",
            "marks": 1.0,
            "topic_id": "comprehension",
            "subtopic_id": "reading-comprehension",
            "passage": {
                "id": "psg_1",
                "kind": "Comprehension",
                "title": "Passage A",
                "text": "Adura had learned to read the room.",
            },
        },
    }
    directory = FIXTURE_DIR
    path = directory / "jamb-use-of-english-2025.json"
    path.write_text(json.dumps({"recorded_at": "2026-10-21T00:00:00Z", "items": [payload]}))
    try:
        source = FixtureSource(directory)
        items = _collect(source, _scope())
        item = source.adapt(items[0], _catalog())
    finally:
        path.unlink()

    assert item.passage is not None
    assert item.passage.id == "psg_1"
    assert item.passage.kind is PassageKind.COMPREHENSION
    assert item.passage.exam == "JAMB"
    assert item.passage.subject == "use-of-english"
    assert item.passage.year == 2025
    assert item.content.passage_id == "psg_1"


def _collect(source: FixtureSource, scope: Scope) -> list[SourceItem]:
    async def run() -> list[SourceItem]:
        return [item async for item in source.fetch(scope)]

    items: list[SourceItem] = asyncio.run(run())
    return items


def _scope() -> Scope:
    return Scope(exam="JAMB", subject="use-of-english", year=2025)


def _catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="use-of-english",
        topics=(CatalogTopic(id="comprehension", slug="comprehension", name="Comprehension"),),
        subtopics=(
            CatalogSubtopic(
                id="reading-comprehension",
                slug="reading-comprehension",
                name="Reading comprehension",
                topic_id="comprehension",
            ),
        ),
    )
