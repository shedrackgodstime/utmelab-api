"""The myschool api parser, against a captured response and the live site.

Two kinds of test on purpose. The unit tests run against a fixture so they never
touch the network and never fail because a third party is slow. The live tests
are marked and skipped unless asked for, because a harvester that has only ever
been tested against a hand-written payload is a harvester that finds out about
the real shape in production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from utmelab_bank.errors import SourceError
from utmelab_bank.source.myschool.parser import (
    EXAMS,
    api_last_page,
    figure_url,
    listing_url,
    parse_api_listing,
    parse_api_question,
    parse_listing,
    slug_for,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


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


def envelope(rows: list[dict[str, Any]], *, last_page: int = 21) -> dict[str, Any]:
    return {
        "status": True,
        "data": {
            "subject": {"id": 4, "title": "Physics", "slug": "physics"},
            "exam_types": {"jamb": "JAMB", "waec": "WAEC", "neco": "NECO"},
            "practice_questions": {
                "current_page": 1,
                "data": rows,
                "last_page": last_page,
                "per_page": 5,
                "next_page_url": "https://myschool.ng/api/web/v1/classroom/physics?page=2",
            },
        },
    }


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def test_a_listing_is_read_from_the_practice_questions_object() -> None:
    rows = parse_api_listing(envelope([api_row()]))
    assert len(rows) == 1
    assert rows[0]["id"] == 74347


def test_the_last_page_comes_from_the_envelope() -> None:
    """The old probe counted links on a page that had none."""
    assert api_last_page(envelope([api_row()], last_page=21)) == 21


def test_a_refusal_from_the_api_is_a_refusal() -> None:
    with pytest.raises(SourceError, match="the api refused"):
        parse_api_listing({"status": False, "message": "unauthorised"})


def test_a_response_with_no_data_object_is_refused() -> None:
    with pytest.raises(SourceError, match="no data object"):
        parse_api_listing({"status": True})


def test_a_response_with_no_practice_object_is_refused() -> None:
    with pytest.raises(SourceError, match="no practice_questions"):
        parse_api_listing({"status": True, "data": {}})


def test_an_empty_page_yields_nothing_rather_than_an_error() -> None:
    assert parse_api_listing(envelope([])) == []


def test_the_listing_url_is_the_api_not_the_page() -> None:
    url = listing_url("jamb", "physics", 2025, 3)
    assert url.startswith("https://myschool.ng/api/web/v1/classroom/physics")
    assert "exam_type=jamb" in url
    assert "exam_year=2025" in url
    assert "page=3" in url


def test_the_first_page_carries_no_page_parameter() -> None:
    assert "page=" not in listing_url("jamb", "physics", 2025)


# ---------------------------------------------------------------------------
# A question
# ---------------------------------------------------------------------------


def test_a_row_becomes_a_question() -> None:
    parsed = parse_api_question(api_row(), exam="jamb", subject="physics", year=2025)
    question = parsed.question
    assert question.id == "q_physics_2025_jamb_74347"
    assert question.text.text == "Which of these colours has the longest wavelength?"
    assert [o.id for o in question.options] == ["A", "B", "C"]
    assert question.answer == "A"


def test_the_answer_comes_from_the_api_not_from_a_colour() -> None:
    """The html harvester inferred the key from a background colour."""
    parsed = parse_api_question(
        api_row(options=[
            {"tag": "a", "description": "One", "is_correct": 0},
            {"tag": "b", "description": "Two", "is_correct": 1},
        ]),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert parsed.question.answer == "B"


def test_the_exam_and_year_come_from_the_collection() -> None:
    """The old waec harvester filed every row under subject ``waec``."""
    parsed = parse_api_question(
        api_row(collection={"exam_type": "waec", "exam_year": 2024}),
        exam="jamb",
        subject="english",
        year=2025,
    )
    assert parsed.question.exam == "waec"
    assert parsed.question.year == 2024
    assert parsed.question.subject == "english"


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
    """A guessed key is the one defect a candidate cannot recover from."""
    with pytest.raises(SourceError, match="marked no option correct"):
        parse_api_question(
            api_row(options=[
                {"tag": "a", "description": "One", "is_correct": 0},
                {"tag": "b", "description": "Two", "is_correct": 0},
            ]),
            exam="jamb",
            subject="physics",
            year=2025,
        )


def test_a_row_whose_text_is_empty_once_stripped_is_refused() -> None:
    with pytest.raises(SourceError, match="empty once tags are stripped"):
        parse_api_question(api_row(question="<p>  </p>"), exam="jamb", subject="physics", year=2025)


def test_duplicate_option_tags_are_collapsed() -> None:
    parsed = parse_api_question(
        api_row(options=[
            {"tag": "a", "description": "One", "is_correct": 1},
            {"tag": "a", "description": "One again", "is_correct": 0},
            {"tag": "b", "description": "Two", "is_correct": 0},
        ]),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert [o.id for o in parsed.question.options] == ["A", "B"]


def test_options_come_out_in_tag_order_not_api_order() -> None:
    parsed = parse_api_question(
        api_row(options=[
            {"tag": "c", "description": "Three", "is_correct": 0},
            {"tag": "a", "description": "One", "is_correct": 1},
            {"tag": "b", "description": "Two", "is_correct": 0},
        ]),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert [o.id for o in parsed.question.options] == ["A", "B", "C"]


def test_underlines_in_a_stem_survive_as_marks() -> None:
    parsed = parse_api_question(
        api_row(question="<p>The <u>rate</u> of decay.</p>"),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert any(m.kind == "underline" for m in parsed.question.text.inline)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def test_a_filename_becomes_the_url_the_serving_host_uses() -> None:
    assert figure_url("abc.png") == "https://myschool.ng/storage/classroom/abc.png"


def test_a_placeholder_is_not_a_figure() -> None:
    """Downloading it would put a placeholder in the bank as a diagram."""
    assert figure_url("50_0_no_image_placeholder.png") is None
    assert figure_url("some/placeholder.gif") is None


def test_no_image_is_not_a_figure() -> None:
    assert figure_url(None) is None
    assert figure_url("") is None
    assert figure_url("   ") is None


def test_an_absolute_url_is_left_alone() -> None:
    assert figure_url("https://cdn.example/a.png") == "https://cdn.example/a.png"
    assert figure_url("//cdn.example/a.png") == "https://cdn.example/a.png"


def test_a_figure_becomes_a_mark_at_the_end_of_the_stem() -> None:
    parsed = parse_api_question(
        api_row(question="<p>The diagram above shows a field.</p>", image="fig.png"),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    marks = [m for m in parsed.question.text.inline if m.kind == "image"]
    assert len(marks) == 1
    assert marks[0].url == "https://myschool.ng/storage/classroom/fig.png"
    assert marks[0].start == len(parsed.question.text.text)
    assert parsed.figures


def test_a_stem_talking_about_a_figure_with_none_is_flagged() -> None:
    parsed = parse_api_question(
        api_row(question="<p>The diagram above shows a field.</p>"),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert parsed.missing_figure
    assert not parsed.figures


def test_a_placeholder_does_not_count_as_the_figure() -> None:
    parsed = parse_api_question(
        api_row(
            question="<p>The diagram above shows a field.</p>",
            image="50_0_no_image_placeholder.png",
        ),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert parsed.missing_figure


def test_a_promised_stimulus_is_noticed() -> None:
    parsed = parse_api_question(
        api_row(question="<p>Using the information below, choose one.</p>"),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert parsed.promises_stimulus


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_the_payload_hash_differs_for_a_different_answer() -> None:
    one = parse_api_question(api_row(), exam="jamb", subject="physics", year=2025)
    two = parse_api_question(
        api_row(options=[
            {"tag": "a", "description": "Red", "is_correct": 0},
            {"tag": "b", "description": "Blue", "is_correct": 1},
        ]),
        exam="jamb",
        subject="physics",
        year=2025,
    )
    assert one.payload_hash != two.payload_hash


def test_the_payload_hash_is_the_same_for_the_same_row() -> None:
    one = parse_api_question(api_row(), exam="jamb", subject="physics", year=2025)
    two = parse_api_question(api_row(), exam="jamb", subject="physics", year=2025)
    assert one.payload_hash == two.payload_hash


def test_the_source_url_points_at_the_listing_and_names_the_item() -> None:
    parsed = parse_api_question(api_row(), exam="jamb", subject="physics", year=2025)
    assert parsed.source_url.endswith("#74347")
    assert parsed.source_item_id == "74347"


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------


def test_every_exam_has_a_spec() -> None:
    assert set(EXAMS) == {"jamb", "waec", "neco"}


def test_the_map_is_the_only_source_of_slugs() -> None:
    """A fallback here is how a subject gets crawled under one name and merged
    under another. The archive refused to allow it and so does this."""
    from utmelab_bank.errors import SourceError

    assert slug_for("jamb", "use-of-english") == "english-language"
    with pytest.raises(SourceError, match="not in the map"):
        slug_for("jamb", "Some New Subject")
    with pytest.raises(SourceError, match="not in the map"):
        slug_for("waec", "use-of-english")


def test_the_reverse_direction_is_separate() -> None:
    """Both sides of a pair in one map would make two subjects interchangeable."""
    from utmelab_bank.source.myschool.parser import catalog_for

    assert catalog_for("jamb", "fine-arts") == "art"
    assert catalog_for("jamb", "english-language") == "use-of-english"


def test_the_html_listing_carries_no_question_links() -> None:
    """Pinned because it is true and surprising: the page is navigation only.

    If the site ever starts rendering links, this fails and we learn that the
    html path became viable, which is worth knowing.
    """
    markup = (
        '<a href="/classroom/jamb-syllabus/jamb">syllabus</a>'
        '<a href="/classroom/video-lessons?subject=jamb">videos</a>'
    )
    assert parse_listing(markup) == []


def test_the_html_listing_still_parses_links_when_there_are_some() -> None:
    """The archive's pattern, which carries the exam and year with the link."""
    markup = (
        '<a href="/classroom/physics/74347?exam_type=jamb&exam_year=2025">q</a>'
        '<a href="/classroom/physics/74348?exam_type=jamb&amp;exam_year=2025">q</a>'
        '<a href="/classroom/physics/74348?exam_type=jamb&amp;exam_year=2025">dupe</a>'
    )
    assert parse_listing(markup) == [("physics", "74347"), ("physics", "74348")]


def test_the_captured_response_still_parses() -> None:
    """A fixture from the real site, so a shape change is caught offline."""
    if not (FIXTURES / "myschool_physics_page1.json").is_file():
        pytest.skip("no captured response")
    payload = load_fixture("myschool_physics_page1.json")
    rows = parse_api_listing(payload)
    assert rows
    assert api_last_page(payload) >= 1
    parsed = parse_api_question(rows[0], exam="jamb", subject="physics", year=2025)
    assert parsed.question.text.text
    assert parsed.question.answer


# ---------------------------------------------------------------------------
# The live site, only when asked for
# ---------------------------------------------------------------------------


@pytest.mark.live
async def test_the_live_api_still_answers() -> None:
    """Marked live. Run it with ``pytest -m live``."""
    from utmelab_bank.config import load
    from utmelab_bank.source.http import PoliteSession

    config = load()
    async with PoliteSession(config) as session:
        payload = await session.get_json(listing_url("jamb", "physics", 2025))
    rows = parse_api_listing(payload)
    assert rows, "the api returned no rows for physics 2025"
    parsed = parse_api_question(rows[0], exam="jamb", subject="physics", year=2025)
    assert parsed.question.options
    assert parsed.question.answer
