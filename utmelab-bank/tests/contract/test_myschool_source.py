"""The myschool source, against a captured API response.

The unit tests never touch the network. The recorded page is the real site's
shape, so a field rename on either side fails here before a scrape run finds
it. The live test in ``tests/live`` is the one that proves the site still
answers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from utmelab_bank.adapters.sources import KNOWN_SOURCES, create_source
from utmelab_bank.adapters.sources.myschool import MyschoolSource
from utmelab_bank.adapters.sources.myschool.errors import SourceError
from utmelab_bank.adapters.sources.myschool.parser import (
    api_last_page,
    figure_url,
    listing_url,
    parse_api_listing,
    parse_api_question,
    slug_for,
)
from utmelab_bank.adapters.sources.myschool.text import clean_inline
from utmelab_bank.domain.enums import InlineKind, SourceCapability
from utmelab_bank.domain.models import Scope, SourceItem
from utmelab_bank.domain.ports import Source

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCOPE = Scope(exam="JAMB", subject="physics", year=2025)


def load_fixture() -> dict[str, Any]:
    value = json.loads((FIXTURES / "myschool_physics_page1.json").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def single_page() -> dict[str, Any]:
    payload = load_fixture()
    practice = payload["data"]["practice_questions"]
    practice["last_page"] = 1
    practice["next_page_url"] = None
    return payload


def api_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": 74347,
        "question": "<p>Which of these colours has the longest wavelength?</p>",
        "options": [
            {"id": 1, "tag": "a", "description": "Red", "is_correct": 1},
            {"id": 2, "tag": "b", "description": "Blue", "is_correct": 0},
            {"id": 3, "tag": "c", "description": "Green", "is_correct": 0},
        ],
        "image": None,
        "collection": {"id": 1273, "exam_year": 2025, "exam_type": "jamb"},
    }
    row.update(overrides)
    return row


def envelope(rows: list[dict[str, Any]], *, last_page: int = 1) -> dict[str, Any]:
    return {
        "status": True,
        "data": {
            "subject": {"id": 4, "title": "Physics", "slug": "physics"},
            "practice_questions": {
                "current_page": 1,
                "data": rows,
                "last_page": last_page,
                "per_page": 5,
            },
        },
    }


def source_with_payload(payload: dict[str, Any]) -> tuple[MyschoolSource, httpx.AsyncClient]:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MyschoolSource(client=client, delay=0.0), client


async def collect(source: MyschoolSource, scope: Scope = SCOPE) -> list[SourceItem]:
    return [item async for item in source.fetch(scope)]


# ── the port and the map ────────────────────────────────────────────────────


async def test_the_source_matches_the_port() -> None:
    source: Source = create_source("myschool")
    assert isinstance(source, Source)
    assert isinstance(source, MyschoolSource)
    assert source.needs_catalog is False
    assert source.profile.name == "myschool"
    assert source.profile.capabilities.supports(SourceCapability.FIGURES)
    assert source.profile.capabilities.supports(SourceCapability.MARKS)
    assert "myschool" in KNOWN_SOURCES
    await source.close()


@pytest.mark.asyncio
async def test_fetch_filters_old_collections_before_parsing() -> None:
    old = api_row(
        id=1,
        question="<p>old malformed row</p>",
        options=[{"tag": "a", "description": "only one", "is_correct": 1}],
        collection={"exam_year": 2016, "exam_type": "jamb"},
    )
    current = api_row(id=2)
    source, client = source_with_payload(envelope([old, current]))
    try:
        rows = await collect(source)
    finally:
        await client.aclose()

    assert [row.source_item_id for row in rows] == ["2"]


def test_the_map_is_the_only_source_of_slugs() -> None:
    assert slug_for("JAMB", "use-of-english") == "english-language"
    assert slug_for("JAMB", "biology") == "biology"
    with pytest.raises(SourceError, match="not in the map"):
        slug_for("JAMB", "some-new-subject")


def test_waec_active_subjects_use_their_recorded_source_slugs() -> None:
    expected = {
        "agricultural-science": "agricultural-science",
        "animal-husbandry": "animal-husbandry",
        "biology": "biology",
        "book-keeping": "book-keeping",
        "catering-craft": "catering-craft-practice",
        "chemistry": "chemistry",
        "further-mathematics": "further-mathematics",
        "insurance": "insurance",
        "marketing": "marketing",
        "office-practice": "office-practice",
    }

    assert {subject: slug_for("WAEC", subject) for subject in expected} == expected


def test_waec_does_not_guess_unsupported_subjects() -> None:
    for subject in ("basic-science", "basic-technology", "home-economics"):
        with pytest.raises(SourceError, match="not in the map"):
            slug_for("WAEC", subject)


def test_waec_catalog_ready_subjects_match_syllabus_inputs() -> None:
    expected = {
        "agricultural-science": "agricultural-science",
        "biology": "biology",
        "book-keeping": "book-keeping",
        "catering-craft": "catering-craft-practice",
        "chemistry": "chemistry",
        "christian-religious-studies": "christian-religious-knowledge-crk",
        "civic-education": "civic-education",
        "computer-studies": "computer-studies",
        "data-processing": "data-processing",
        "economics": "economics",
        "english-language": "english-language",
        "financial-accounting": "accounts-principles-of-accounts",
        "foods-and-nutrition": "food-and-nutrition",
        "french": "french",
        "geography": "geography",
        "home-management": "home-management",
        "government": "government",
        "general-mathematics": "mathematics",
        "health-education": "health-education",
        "islamic-studies": "islamic-religious-knowledge-irk",
        "literature-in-english": "literature-in-english",
        "music": "music",
        "physics": "physics",
        "nigerian-history": "history",
        "office-practice": "office-practice",
        "physical-education": "physical-education",
        "technical-drawing": "technical-drawing",
        "visual-arts": "fine-arts",
        "yoruba": "yoruba",
        "igbo": "igbo",
        "hausa": "hausa",
    }

    assert {subject: slug_for("WAEC", subject) for subject in expected} == expected


# ── the api envelope ────────────────────────────────────────────────────────


def test_the_listing_url_is_the_api() -> None:
    url = listing_url("jamb", "physics", 2025, 3)
    assert url.startswith("https://myschool.ng/api/web/v1/classroom/physics")
    assert "exam_type=jamb" in url
    assert "exam_year=2025" in url
    assert "page=3" in url


def test_the_first_page_carries_no_page_parameter() -> None:
    assert "page=" not in listing_url("jamb", "physics", 2025)


def test_a_listing_is_read_from_the_practice_questions_object() -> None:
    rows = parse_api_listing(envelope([api_row()]))
    assert len(rows) == 1
    assert rows[0]["id"] == 74347


def test_the_last_page_comes_from_the_envelope() -> None:
    assert api_last_page(envelope([api_row()], last_page=21)) == 21


def test_a_refusal_from_the_api_is_a_refusal() -> None:
    with pytest.raises(SourceError, match="the api refused"):
        parse_api_listing({"status": False, "message": "unauthorised"})


def test_a_response_with_no_data_object_is_refused() -> None:
    with pytest.raises(SourceError, match="no data object"):
        parse_api_listing({"status": True})


def test_an_empty_page_yields_nothing() -> None:
    assert parse_api_listing(envelope([])) == []


# ── a question and its payload ──────────────────────────────────────────────


def test_a_row_becomes_the_source_payload() -> None:
    parsed = parse_api_question(api_row(), exam="jamb", subject="physics", year=2025)

    assert parsed.source_item_id == "74347"
    assert parsed.exam == "jamb"
    assert parsed.year == 2025
    assert parsed.payload["stem"] == "Which of these colours has the longest wavelength?"
    assert [option["id"] for option in parsed.payload["options"]] == ["A", "B", "C"]
    assert parsed.payload["answer"] == "A"
    assert parsed.payload["marks"] == 1.0


def test_underlines_survive_as_marks() -> None:
    parsed = parse_api_question(
        api_row(question="<p>The <u>rate</u> of decay.</p>"),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    marks = parsed.payload["stem_inline"]
    assert any(mark["kind"] == "underline" for mark in marks)


def test_inserted_html_survives_as_an_underline_mark() -> None:
    parsed = parse_api_question(
        api_row(question="<p>The <ins>rate</ins> of decay.</p>"),
        exam="waec",
        subject="english-language",
        year=2025,
    )
    marks = parsed.payload["stem_inline"]
    assert any(mark["kind"] == "underline" for mark in marks)


def test_the_answer_comes_from_the_api() -> None:
    parsed = parse_api_question(
        api_row(
            options=[
                {"tag": "a", "description": "One", "is_correct": 0},
                {"tag": "b", "description": "Two", "is_correct": 1},
            ]
        ),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert parsed.payload["answer"] == "B"


def test_the_collection_names_the_exam_and_year() -> None:
    parsed = parse_api_question(
        api_row(collection={"exam_type": "waec", "exam_year": 2024}),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert parsed.exam == "waec"
    assert parsed.year == 2024


def test_a_row_with_no_id_is_refused() -> None:
    with pytest.raises(SourceError, match="no id"):
        parse_api_question(api_row(id=""), exam="jamb", subject="physics", year=2025)


def test_a_row_with_no_question_text_is_refused() -> None:
    with pytest.raises(SourceError, match="no question text"):
        parse_api_question(api_row(question=""), exam="jamb", subject="physics", year=2025)


def test_a_row_with_one_option_is_refused() -> None:
    with pytest.raises(SourceError, match="fewer than two usable options"):
        parse_api_question(
            api_row(options=[{"tag": "a", "description": "Only", "is_correct": 1}]),
            exam="jamb",
            subject="physics",
            year=2025,
        )


def test_a_row_with_no_correct_option_is_refused() -> None:
    with pytest.raises(SourceError, match="marked no option correct"):
        parse_api_question(
            api_row(
                options=[
                    {"tag": "a", "description": "One", "is_correct": 0},
                    {"tag": "b", "description": "Two", "is_correct": 0},
                ]
            ),
            exam="jamb",
            subject="physics",
            year=2025,
        )


def test_duplicate_option_tags_are_collapsed() -> None:
    parsed = parse_api_question(
        api_row(
            options=[
                {"tag": "a", "description": "One", "is_correct": 1},
                {"tag": "a", "description": "One again", "is_correct": 0},
                {"tag": "b", "description": "Two", "is_correct": 0},
            ]
        ),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert [option["id"] for option in parsed.payload["options"]] == ["A", "B"]


def test_options_come_out_in_tag_order() -> None:
    parsed = parse_api_question(
        api_row(
            options=[
                {"tag": "c", "description": "Three", "is_correct": 0},
                {"tag": "a", "description": "One", "is_correct": 1},
                {"tag": "b", "description": "Two", "is_correct": 0},
            ]
        ),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert [option["id"] for option in parsed.payload["options"]] == ["A", "B", "C"]


# ── figures ─────────────────────────────────────────────────────────────────


def test_a_filename_becomes_the_storage_url() -> None:
    assert figure_url("abc.png") == "https://myschool.ng/storage/classroom/abc.png"


def test_a_placeholder_is_not_a_figure() -> None:
    assert figure_url("50_0_no_image_placeholder.png") is None
    assert figure_url("some/placeholder.gif") is None


def test_an_absolute_url_is_left_alone() -> None:
    assert figure_url("https://cdn.example/a.png") == "https://cdn.example/a.png"
    assert figure_url("//cdn.example/a.png") == "https://cdn.example/a.png"


def test_the_row_image_becomes_an_end_mark_and_a_media_ref() -> None:
    parsed = parse_api_question(
        api_row(question="<p>The diagram above shows a field.</p>", image="fig.png"),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    images = [mark for mark in parsed.payload["stem_inline"] if mark["kind"] == "image"]
    assert len(images) == 1
    assert images[0]["url"] == "https://myschool.ng/storage/classroom/fig.png"
    assert images[0]["start"] == len(parsed.payload["stem"])
    assert parsed.payload["media"][0]["url"] == images[0]["url"]


def test_an_inline_image_is_resolved_and_backed_by_media() -> None:
    text, marks = clean_inline('<p>Look <img src="/storage/classroom/x.png" alt="x"> here.</p>')
    assert text == "Look here."
    image = next(mark for mark in marks if mark.kind is InlineKind.IMAGE)
    assert image.url == "/storage/classroom/x.png"

    parsed = parse_api_question(
        api_row(question='<p>Look <img src="/storage/classroom/x.png" alt="x"> here.</p>'),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert parsed.payload["media"][0]["url"] == "https://myschool.ng/storage/classroom/x.png"
    assert parsed.payload["stem_inline"][0]["url"] == parsed.payload["media"][0]["url"]


def test_the_captured_page_still_parses() -> None:
    payload = load_fixture()
    rows = parse_api_listing(payload)
    assert rows
    parsed = parse_api_question(rows[0], exam="jamb", subject="physics", year=2025)
    assert parsed.payload["stem"]
    assert parsed.payload["answer"]


# ── the source over http ────────────────────────────────────────────────────


async def test_fetch_returns_provenance_and_the_payload() -> None:
    source, client = source_with_payload(single_page())
    try:
        items = await collect(source)
    finally:
        await client.aclose()

    assert items
    item = items[0]
    assert item.source == "myschool"
    assert item.external_key == "myschool:74347"
    assert item.scope == SCOPE
    assert item.source_version == "2.0.0"
    assert item.payload["stem"]
    assert "/classroom/physics/74347" in str(item.source_url)
    assert "exam_type=jamb" in str(item.source_url)


async def test_the_source_adapts_without_a_catalog() -> None:
    source, client = source_with_payload(single_page())
    try:
        item = (await collect(source))[0]
        adapted = source.adapt(item, None)
    finally:
        await client.aclose()

    assert adapted.catalog is None
    assert adapted.content.answer == "a"
    assert [option.id for option in adapted.content.options] == ["a", "b", "c", "d"]
    assert adapted.state.value == "adapted"
    assert adapted.hashes is not None


async def test_probe_reports_the_first_page() -> None:
    source, client = source_with_payload(load_fixture())
    try:
        coverage = await source.probe(SCOPE)
    finally:
        await client.aclose()

    assert coverage.item_count == 5
    assert coverage.has_more is True


async def test_a_row_with_no_answer_is_a_per_row_failure() -> None:
    row = api_row(
        options=[
            {"tag": "a", "description": "One", "is_correct": 0},
            {"tag": "b", "description": "Two", "is_correct": 0},
        ]
    )
    source, client = source_with_payload(envelope([row]))
    try:
        items = await collect(source)
    finally:
        await client.aclose()

    assert len(items) == 1
    assert items[0].source_item_id == "74347"
    assert "source.error" in " ".join(source.validate(items[0]))


async def test_a_row_from_another_year_is_filtered_out() -> None:
    row = api_row(collection={"exam_year": 2024, "exam_type": "jamb"})
    source, client = source_with_payload(envelope([row]))
    try:
        items = await collect(source)
    finally:
        await client.aclose()

    assert items == []


async def test_a_4xx_is_not_retried() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    source = MyschoolSource(client=client, delay=0.0)
    try:
        with pytest.raises(SourceError, match="answered 404"):
            await source.probe(SCOPE)
    finally:
        await client.aclose()

    assert calls == 1


async def test_the_captured_page_reaches_a_staging_row() -> None:
    """The fixture path and the live path share one adapter."""
    source, client = source_with_payload(single_page())
    try:
        item = (await collect(source))[0]
        raw = source.adapt(item, None)
    finally:
        await client.aclose()

    assert raw.provenance.scope == SCOPE
    assert raw.hashes is not None
    assert len(raw.hashes.content_hash) == 64
