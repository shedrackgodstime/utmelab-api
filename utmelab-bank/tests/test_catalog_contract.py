"""The semantic catalog contract: what a row must look like to be usable."""

from utmelab_bank.catalog.contract import (
    MAX_NAME_CHARS,
    name_defects,
    subject_defects,
    summarise,
)


def topic(slug: str, name: str) -> dict[str, str]:
    return {"slug": slug, "name": name}


def subtopic(slug: str, name: str, topic_slug: str) -> dict[str, str]:
    return {"slug": slug, "name": name, "topic": topic_slug}


def test_a_short_phrase_passes() -> None:
    assert name_defects("The family") == []


def test_a_name_at_the_limit_passes() -> None:
    assert name_defects("X" * MAX_NAME_CHARS) == []


def test_a_name_over_the_limit_fails() -> None:
    assert name_defects("X" * (MAX_NAME_CHARS + 1)) == [
        ("too_long", f"{MAX_NAME_CHARS + 1} chars, max {MAX_NAME_CHARS}")
    ]


def test_list_markers_are_rejected() -> None:
    for name in ("(a) Definitions", "(ii) Hospitality", "b) Components", "3. Mining"):
        assert ("list_marker", "starts with a list marker") in name_defects(name)


def test_a_number_inside_a_chemical_name_is_not_a_marker() -> None:
    assert name_defects("2,4-dinitrophenylhydrazine") == []


def test_a_bracket_fragment_is_rejected() -> None:
    assert name_defects("(for internal use and for export), problems") == [
        ("fragment", "starts mid-sentence inside a bracket")
    ]


def test_a_lowercase_continuation_is_rejected() -> None:
    assert name_defects("types of drawing and applications") == [
        ("lowercase_start", "starts with a lowercase word")
    ]


def test_duplicate_topic_names_in_one_subject_are_errors() -> None:
    defects = subject_defects(
        "geography",
        [topic("t1", "Trade"), topic("t2", "Trade")],
        [
            subtopic("s1", "Import trade", "t1"),
            subtopic("s2", "Export trade", "t2"),
        ],
    )
    assert [(d.slug, d.rule) for d in defects] == [("t2", "duplicate_name")]


def test_duplicate_subtopic_names_under_one_topic_are_errors() -> None:
    defects = subject_defects(
        "biology",
        [topic("t1", "Cell")],
        [
            subtopic("s1", "Structure", "t1"),
            subtopic("s2", "Structure", "t1"),
        ],
    )
    assert [(d.slug, d.rule) for d in defects] == [("s2", "duplicate_name")]


def test_the_same_subtopic_name_under_two_topics_is_allowed() -> None:
    defects = subject_defects(
        "biology",
        [topic("t1", "Cell"), topic("t2", "Tissue")],
        [
            subtopic("s1", "Structure", "t1"),
            subtopic("s2", "Structure", "t2"),
        ],
    )
    assert defects == []


def test_summarise_counts_by_subject_and_rule() -> None:
    defects = subject_defects(
        "geography",
        [topic("t1", "Trade"), topic("t2", "Trade")],
        [subtopic("s1", "(a) Import trade", "t1")],
    )
    counts = summarise(defects)
    assert counts[("geography", "duplicate_name")] == 1
    assert counts[("geography", "list_marker")] == 1
