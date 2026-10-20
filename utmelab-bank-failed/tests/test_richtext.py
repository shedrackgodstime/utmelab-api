"""RichText construction, repair and joining.

Marks are byte ranges. Every join, every repair and every passage block has to
keep those ranges pointing at the same words, because a mark one character off
is an underline on the wrong answer.
"""

from __future__ import annotations

import json

from utmelab_bank.model.richtext import Mark, RichText
from utmelab_bank.text.richtext import (
    clean_blocks,
    from_json,
    join_rich,
    merge_words,
    offset_of,
    rt,
    rt_json,
    snap,
    unescape_segment,
)


def _mark(kind: str, start: int, length: int) -> Mark:
    return Mark(kind=kind, start=start, len=length)


def test_rt_returns_the_text_and_a_json_marks_column() -> None:
    text, marks = rt("hello", [_mark("bold", 0, 5)])

    assert text == "hello"
    assert json.loads(marks)[0]["kind"] == "bold"


def test_rt_accepts_a_plain_mapping() -> None:
    _, marks = rt("hello", [{"kind": "italic", "start": 0, "len": 5}])

    assert json.loads(marks)[0]["kind"] == "italic"


def test_rt_json_serialises_models_and_mappings() -> None:
    payload = json.loads(rt_json([_mark("bold", 0, 2), {"kind": "italic", "start": 3, "len": 2}]))

    assert [entry["kind"] for entry in payload] == ["bold", "italic"]


def test_from_json_handles_an_empty_column() -> None:
    rich = from_json("plain", None)

    assert rich.text == "plain"
    assert rich.inline == []


def test_from_json_handles_a_broken_column() -> None:
    rich = from_json("plain", "{not json")

    assert rich.text == "plain"
    assert rich.inline == []


def test_from_json_rebuilds_marks() -> None:
    rich = from_json("hello", rt_json([_mark("bold", 0, 5)]))

    assert rich.text == "hello"
    assert rich.inline[0].kind == "bold"
    assert rich.inline[0].len == 5


def test_offset_of_returns_none_when_the_phrase_is_absent() -> None:
    assert offset_of("hello", "world") is None
    assert offset_of("hello world", "world") == 6


def test_snap_delegates_to_the_model_rule() -> None:
    """A partial word grows to the whole word, which is the model's rule."""
    snapped = snap("hello", [_mark("bold", 0, 2)])

    assert [(mark.start, mark.len) for mark in snapped] == [(0, 5)]


def test_join_rich_skips_empty_parts_and_shifts_marks() -> None:
    first = RichText(text="one", inline=[_mark("bold", 0, 3)])
    blank = RichText(text="", inline=[])
    second = RichText(text="two", inline=[_mark("italic", 0, 3)])

    joined = join_rich([first, blank, second])

    assert joined.text == "one two"
    assert [(mark.kind, mark.start, mark.len) for mark in joined.inline] == [
        ("bold", 0, 3),
        ("italic", 4, 3),
    ]


def test_join_rich_uses_the_requested_separator() -> None:
    joined = join_rich([RichText(text="one"), RichText(text="two")], "\n\n")

    assert joined.text == "one\n\ntwo"


def test_clean_blocks_turns_fragments_into_paragraphs_with_marks() -> None:
    rich = clean_blocks(["<b>One</b>", "", "<i>Two</i>"])

    assert rich.text == "One\n\nTwo"
    assert [(mark.kind, mark.start, mark.len) for mark in rich.inline] == [
        ("bold", 0, 3),
        ("italic", 5, 3),
    ]


def test_merge_words_collapses_the_seams() -> None:
    assert merge_words(["what is", " the", "", "function?"]) == "what is the function?"
    assert merge_words([" ", ""]) == ""


def test_unescape_segment_decodes_entities_once() -> None:
    assert unescape_segment("30&deg; and &amp;") == "30° and &"
    assert unescape_segment("&amp;amp;") == "&"
