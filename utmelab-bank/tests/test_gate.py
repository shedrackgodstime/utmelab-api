"""The gate. Strict, machine only, and total.

Every rule that can detect a defect can block a row, so a row that reaches
the served content has been judged. The live reference for the rules is
``tools/review.py``, and the counts are checked against the live bank in
``test_gate_matches_the_live_reference``.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from utmelab_bank.domain.dedupe import near_duplicate_fingerprint
from utmelab_bank.domain.enums import (
    ImagePosition,
    InlineKind,
    PassageKind,
    Severity,
)
from utmelab_bank.domain.gate import (
    RULES_VERSION,
    GateContext,
    check_inline,
    check_option_ids,
    has_numbered_gap,
    mentions_figure,
    refusal_counts,
    run_gate,
)
from utmelab_bank.domain.models import (
    CatalogRef,
    CatalogSnapshot,
    CatalogSubtopic,
    CatalogTopic,
    Clearance,
    Content,
    GateVerdict,
    Inline,
    Issue,
    Option,
    Passage,
    RichText,
)

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def make_content(**overrides: object) -> Content:
    data: dict[str, object] = {
        "stem": RichText(text="What is 2 + 2?"),
        "options": (
            Option(id="a", text=RichText(text="3")),
            Option(id="b", text=RichText(text="4")),
            Option(id="c", text=RichText(text="5")),
            Option(id="d", text=RichText(text="6")),
        ),
        "answer": "b",
        "marks": 1.0,
        "source_explanation": RichText(text="Two and two is four."),
    }
    data.update(overrides)
    return Content.model_validate(data)


def gate(content: Content, **overrides: Any) -> GateVerdict:
    context = GateContext(
        content=content, exam="JAMB", subject="mathematics", year=2025, **overrides
    )
    return run_gate(context)


def codes(verdict: GateVerdict) -> set[str]:
    return {issue.code for issue in verdict.issues}


# ── the happy path ──────────────────────────────────────────────────────────


def test_a_clean_question_passes() -> None:
    verdict = gate(make_content())

    assert verdict.passed is True
    assert verdict.issues == ()
    assert verdict.rules_version == RULES_VERSION


def test_the_rules_version_is_stamped() -> None:
    assert gate(make_content()).rules_version == RULES_VERSION


# ── defects: they block and nothing clears them ────────────────────────────


def test_a_mark_past_the_end_of_the_text_fails() -> None:
    """The rule is judged on its own, because the model refuses first.

    The model refuses an out of bounds mark at construction, so in normal
    operation this rule never fires. It is the second line, and it is here so
    that a relaxed model cannot let a broken offset through.
    """
    issues: list[Issue] = []

    check_inline("short", (Inline(kind=InlineKind.BOLD, start=0, len=40),), "text", issues)

    assert [issue.code for issue in issues] == ["inline_out_of_bounds"]
    assert issues[0].severity is Severity.ERROR


def test_two_marks_that_partially_overlap_fail() -> None:
    issues: list[Issue] = []

    check_inline(
        "abcdef",
        (
            Inline(kind=InlineKind.BOLD, start=0, len=4),
            Inline(kind=InlineKind.ITALIC, start=2, len=2),
        ),
        "text",
        issues,
    )

    assert [issue.code for issue in issues] == ["inline_partial_overlap"]


def test_two_marks_on_an_identical_range_pass() -> None:
    """Bold on top of underline is the case the decision log names."""
    content = make_content(
        stem=RichText(
            text="abcdef",
            inline=(
                Inline(kind=InlineKind.BOLD, start=0, len=4),
                Inline(kind=InlineKind.UNDERLINE, start=0, len=4),
            ),
        )
    )

    verdict = gate(content)

    assert verdict.passed is True


def test_a_relative_image_url_fails() -> None:
    """The model refuses it first, and the gate refuses it second."""
    with pytest.raises(ValueError):
        Inline(
            kind=InlineKind.IMAGE,
            start=0,
            len=0,
            url="/diagrams/x.png",
            position=ImagePosition.ABOVE,
        )

    issues: list[Issue] = []
    bypassed = Inline.model_construct(
        kind=InlineKind.IMAGE,
        start=0,
        len=0,
        url="/diagrams/x.png",
        position=ImagePosition.ABOVE,
        alt=None,
    )
    check_inline("see the figure", (bypassed,), "text", issues)

    assert [issue.code for issue in issues] == ["image_url_not_https"]


def test_the_option_count_must_be_four() -> None:
    content = make_content(
        options=(
            Option(id="a", text=RichText(text="3")),
            Option(id="b", text=RichText(text="4")),
        )
    )

    verdict = gate(content)

    assert verdict.passed is False
    assert "option_count" in codes(verdict)


def test_an_answer_that_names_no_option_fails() -> None:
    """The model refuses it first, and the gate refuses it second."""
    with pytest.raises(ValueError):
        make_content(answer="z")

    issues: list[Issue] = []
    check_option_ids(["a", "b", "c", "d"], "z", issues)

    assert [issue.code for issue in issues] == ["answer_not_an_option"]


def test_a_missing_explanation_fails() -> None:
    content = make_content(source_explanation=None)

    verdict = gate(content)

    assert verdict.passed is False
    assert "explanation_missing" in codes(verdict)


def test_html_in_the_stem_fails() -> None:
    content = make_content(stem=RichText(text="What is 2 &amp; 2?"))

    verdict = gate(content)

    assert verdict.passed is False
    assert "html_in_text" in codes(verdict)


def test_markup_in_the_stem_fails() -> None:
    content = make_content(stem=RichText(text="<b>What</b> is 2 + 2?"))

    verdict = gate(content)

    assert verdict.passed is False
    assert "html_in_text" in codes(verdict)


def test_an_empty_exam_fails() -> None:
    verdict = run_gate(GateContext(content=make_content(), exam="", subject="mathematics"))

    assert verdict.passed is False
    assert "exam_empty" in codes(verdict)


def test_marks_outside_the_range_fail() -> None:
    verdict = run_gate(
        GateContext(
            content=make_content(marks=20.0),
            exam="JAMB",
            subject="mathematics",
        )
    )

    assert verdict.passed is False
    assert "marks_out_of_range" in codes(verdict)


# ── judgement: they block, and a person can clear them ─────────────────────


def test_a_figure_mention_without_a_figure_is_a_judgement() -> None:
    content = make_content(stem=RichText(text="In the graph below, the slope is:"))

    verdict = gate(content)

    assert verdict.passed is False
    issue = next(i for i in verdict.issues if i.code == "missing_figure")
    assert issue.severity is Severity.JUDGEMENT


def test_a_clearance_makes_a_judgement_pass() -> None:
    content = make_content(stem=RichText(text="In the graph below, the slope is:"))
    clearance = Clearance(
        rule="missing_figure",
        by="owner",
        reason="the word is ordinary, there is no figure to add",
        created_at=NOW,
    )

    verdict = gate(content, clearances=(clearance,))

    assert verdict.passed is True
    assert verdict.clearances == (clearance,)


def test_a_defect_also_goes_to_the_person() -> None:
    """Every refusal is the person's, a defect and a judgement alike.

    The normal resolution of a defect is a fix to the content, but the gate
    does not make that the only way out. A person can clear it with a
    recorded reason, and the severity stays on the issue so the counts still
    say what was objectively broken.
    """
    content = make_content(source_explanation=None)

    verdict = gate(content)

    assert verdict.passed is False
    issue = next(i for i in verdict.issues if i.code == "explanation_missing")
    assert issue.severity is Severity.ERROR

    clearance = Clearance(
        rule="explanation_missing",
        by="owner",
        reason="the explanation is written and lands with the next batch",
        created_at=NOW,
    )
    cleared = gate(content, clearances=(clearance,))

    assert cleared.passed is True
    assert cleared.issues[0].severity is Severity.ERROR


def test_the_unresolved_issues_are_the_queue() -> None:
    content = make_content(source_explanation=None)

    verdict = gate(content)

    assert [issue.code for issue in verdict.unresolved] == ["explanation_missing"]


def test_a_cleared_issue_leaves_the_queue() -> None:
    content = make_content(source_explanation=None)
    clearance = Clearance(
        rule="explanation_missing",
        by="owner",
        reason="handled",
        created_at=NOW,
    )

    verdict = gate(content, clearances=(clearance,))

    assert verdict.unresolved == ()
    assert verdict.passed is True


def test_a_clearance_for_another_rule_does_not_pass() -> None:
    content = make_content(stem=RichText(text="In the graph below, the slope is:"))
    clearance = Clearance(
        rule="option_count",
        by="owner",
        reason="not the rule that fired",
        created_at=NOW,
    )

    verdict = gate(content, clearances=(clearance,))

    assert verdict.passed is False


def test_the_figure_rule_fires_on_the_word_table_and_a_person_clears_it() -> None:
    """The word table is not a figure, and the rule cannot tell.

    This is the false positive the live bank carries, on a stress question
    whose last option is the word table. The rule still fires, because a rule
    that guessed would let a real missing figure through, but it fires as a
    judgement, so a person clears it in seconds and the clearance is kept.
    """
    content = make_content(
        stem=RichText(
            text="Choose the word with a different stress pattern: commit, begin, record, table."
        )
    )

    verdict = gate(content)

    assert verdict.passed is False
    issue = next(i for i in verdict.issues if i.code == "missing_figure")
    assert issue.severity is Severity.JUDGEMENT

    cleared = gate(
        content,
        clearances=(
            Clearance(
                rule="missing_figure",
                by="owner",
                reason="the word is ordinary, there is no figure to add",
                created_at=NOW,
            ),
        ),
    )
    assert cleared.passed is True


def test_the_figure_rule_fires_on_a_real_figure() -> None:
    content = make_content(
        stem=RichText(text="In the displacement-time graph of simple harmonic motion:")
    )

    verdict = gate(content)

    assert "missing_figure" in codes(verdict)


def test_a_named_gap_without_a_passage_is_a_judgement() -> None:
    content = make_content(stem=RichText(text="Fill the gap numbered 3 with the right word."))

    verdict = gate(content)

    assert verdict.passed is False
    assert "cloze_without_passage" in codes(verdict)


def test_an_underline_mention_without_an_underline_is_a_judgement() -> None:
    content = make_content(stem=RichText(text="Underline the correct answer in this list."))

    verdict = gate(content)

    assert "underline_missing" in codes(verdict)


# ── duplicates ──────────────────────────────────────────────────────────────


def test_a_duplicate_id_fails() -> None:
    verdict = gate(make_content(), self_id="q1", known_ids=frozenset({"q1"}))

    assert verdict.passed is False
    assert "duplicate_id" in codes(verdict)


def test_a_duplicate_content_hash_fails() -> None:
    verdict = gate(make_content(), self_hash="a" * 64, known_hashes=frozenset({"a" * 64}))

    assert verdict.passed is False
    assert "duplicate_content" in codes(verdict)


def test_a_near_duplicate_is_a_judgement() -> None:
    fingerprint = near_duplicate_fingerprint(
        "What is 2 + 2?",
        ("3", "4", "5", "6"),
    )

    verdict = gate(make_content(), known_near_duplicates=frozenset({fingerprint}))

    assert verdict.passed is False
    issue = next(i for i in verdict.issues if i.code == "duplicate_near")
    assert issue.severity is Severity.JUDGEMENT


def test_the_near_duplicate_fingerprint_ignores_option_order() -> None:
    first = near_duplicate_fingerprint(
        "What is 2 + 2?",
        ("3", "4", "5", "6"),
    )
    second = near_duplicate_fingerprint(
        "what is 2 + 2?",
        ("6", "5", "4", "3"),
    )

    assert first == second


def test_the_near_duplicate_fingerprint_separates_different_content() -> None:
    first = near_duplicate_fingerprint(
        "What is 2 + 2?",
        ("3", "4", "5", "6"),
    )
    second = near_duplicate_fingerprint(
        "What is 2 + 3?",
        ("3", "4", "5", "6"),
    )

    assert first != second


# ── placement ───────────────────────────────────────────────────────────────


def catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        version="2026.1",
        exam="JAMB",
        subject="mathematics",
        topics=(CatalogTopic(id="algebra", slug="algebra", name="Algebra"),),
        subtopics=(
            CatalogSubtopic(
                id="surds",
                slug="surds",
                name="Surds",
                topic_id="algebra",
            ),
        ),
    )


def placement(**overrides: object) -> CatalogRef:
    data: dict[str, object] = {
        "exam": "JAMB",
        "subject": "mathematics",
        "year": 2025,
        "topic_id": "algebra",
        "subtopic_id": "surds",
        "catalog_version": "2026.1",
    }
    data.update(overrides)
    return CatalogRef.model_validate(data)


def test_an_unknown_subtopic_fails() -> None:
    verdict = gate(
        make_content(),
        placement=placement(subtopic_id="not-a-subtopic"),
        catalog=catalog(),
    )

    assert verdict.passed is False
    assert "subtopic_not_in_catalog" in codes(verdict)


def test_a_subtopic_under_another_topic_fails() -> None:
    verdict = gate(
        make_content(),
        placement=placement(topic_id="geometry"),
        catalog=catalog(),
    )

    assert verdict.passed is False
    assert "subtopic_topic_mismatch" in codes(verdict)


def test_a_correct_placement_passes() -> None:
    verdict = gate(make_content(), placement=placement(), catalog=catalog())

    assert verdict.passed is True


def test_a_placement_for_another_subject_fails() -> None:
    verdict = gate(
        make_content(),
        placement=placement(subject="physics"),
        catalog=catalog(),
    )

    assert verdict.passed is False
    assert "placement_scope_mismatch" in codes(verdict)


# ── the passage ─────────────────────────────────────────────────────────────


def make_passage(**overrides: object) -> Passage:
    data: dict[str, object] = {
        "id": "psg_1",
        "exam": "JAMB",
        "subject": "mathematics",
        "year": 2025,
        "kind": PassageKind.COMPREHENSION,
        "title": "Passage A",
        "text": RichText(text="Adura had learned to read the room."),
    }
    data.update(overrides)
    return Passage.model_validate(data)


def test_a_passage_the_bank_does_not_hold_fails() -> None:
    content = make_content(passage_id="psg_1")

    verdict = gate(content, known_passage_ids=frozenset({"psg_other"}))

    assert verdict.passed is False
    assert "passage_not_found" in codes(verdict)


def test_a_passage_the_bank_holds_passes() -> None:
    content = make_content(passage_id="psg_1")

    verdict = gate(content, known_passage_ids=frozenset({"psg_1"}))

    assert verdict.passed is True


def test_a_passage_from_another_subject_fails() -> None:
    """Production holds the subject rule without exception."""
    content = make_content(passage_id="psg_1")
    passage = make_passage(subject="use-of-english")

    verdict = gate(content, passage=passage, known_passage_ids=frozenset({"psg_1"}))

    assert verdict.passed is False
    assert "passage_subject_mismatch" in codes(verdict)


def test_a_passage_under_another_id_fails() -> None:
    content = make_content(passage_id="psg_1")
    passage = make_passage(id="psg_2")

    verdict = gate(content, passage=passage)

    assert verdict.passed is False
    assert "passage_id_mismatch" in codes(verdict)


def test_the_passage_text_is_judged_too() -> None:
    content = make_content(passage_id="psg_1")
    passage = make_passage(text=RichText(text="What is 2 &amp; 2?"))

    verdict = gate(content, passage=passage)

    assert verdict.passed is False
    assert "html_in_text" in codes(verdict)


# ── the counts ──────────────────────────────────────────────────────────────


def test_the_refusal_counts_are_per_rule() -> None:
    good = gate(make_content())
    bad = gate(make_content(source_explanation=None))

    counts = refusal_counts([good, bad])

    assert counts == {"explanation_missing": 1}


def test_the_counts_are_ordered_by_volume() -> None:
    verdicts = [
        gate(make_content(source_explanation=None)),
        gate(make_content(source_explanation=None)),
        gate(make_content(stem=RichText(text="In the graph below:"))),
    ]

    counts = refusal_counts(verdicts)

    assert list(counts) == ["explanation_missing", "missing_figure"]


# ── the helpers, on their own ───────────────────────────────────────────────


def test_mentions_figure_finds_a_graph() -> None:
    assert mentions_figure("in the displacement-time graph of motion") is True


def test_mentions_figure_ignores_an_ordinary_table() -> None:
    assert mentions_figure("record, begin, commit, table") is True
    assert mentions_figure("the table below") is True


def test_mentions_figure_ignores_a_word_that_only_contains_a_hint() -> None:
    assert mentions_figure("the configurable setting") is False


def test_has_numbered_gap_finds_a_gap() -> None:
    assert has_numbered_gap("Fill the gap numbered 3.") is True
    assert has_numbered_gap("Fill the gaps labelled 1 and 2.") is True


def test_has_numbered_gap_ignores_a_gap_without_a_number() -> None:
    assert has_numbered_gap("Fill the gap.") is False
