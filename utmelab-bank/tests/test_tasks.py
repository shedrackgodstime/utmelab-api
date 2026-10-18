"""The mechanical gate, text handling, and the task base.

These are the rules that decide whether a row is worth anything, so they get
tested against the specific ways the old harvesters disagreed with each other.
"""

from __future__ import annotations

from typing import Any

import pytest

from utmelab_bank.config import Config
from utmelab_bank.errors import BankError
from utmelab_bank.model.richtext import Mark, RichText, snap_offsets
from utmelab_bank.model.run import RowOutcome
from utmelab_bank.store.repository import Repository
from utmelab_bank.task import run_task
from utmelab_bank.task.base import TaskContext, TaskResult
from utmelab_bank.task.gates import MechanicalGate, judge
from utmelab_bank.text import (
    clean_inline,
    mentions_figure,
    merge_words,
    promises_stimulus,
    slugify,
    strip_tags,
    visible_lines,
)

# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_a_clean_row_passes() -> None:
    verdict = judge(
        text="Which of the following is a noble gas?",
        option_ids=["A", "B", "C", "D"],
        answer="A",
        exam="jamb",
    )
    assert verdict.passed
    assert verdict.reason == ""


def test_a_key_pointing_at_nothing_is_refused() -> None:
    verdict = judge(
        text="A real stem with words in it", option_ids=["A", "B"], answer="D", exam="jamb"
    )
    assert not verdict.passed
    assert verdict.reason == "answer_not_an_option"


def test_duplicate_options_are_refused() -> None:
    verdict = judge(
        text="A real stem with words in it", option_ids=["A", "A"], answer="A", exam="jamb"
    )
    assert "duplicate_options" in verdict.reasons


def test_one_option_is_not_a_question() -> None:
    verdict = judge(text="A real stem with words in it", option_ids=["A"], answer="A", exam="jamb")
    assert "few_options" in verdict.reasons


def test_a_fragment_of_a_page_is_refused() -> None:
    verdict = judge(text="A.", option_ids=["A", "B"], answer="A", exam="jamb")
    assert "stem_too_short" in verdict.reasons


def test_a_figure_hint_with_no_image_is_refused() -> None:
    """The rule that decided usability, in four places with three regexes."""
    verdict = judge(
        text="The arrangement of atoms is shown in the diagram below.",
        option_ids=["A", "B"],
        answer="A",
        marks=[],
    )
    assert "missing_referenced_figure" in verdict.reasons


def test_a_figure_hint_with_an_image_passes() -> None:
    verdict = judge(
        text="The arrangement of atoms is shown in the diagram below.",
        option_ids=["A", "B", "C", "D"],
        answer="A",
        exam="jamb",
        marks=[{"kind": "image", "start": 0, "len": 1, "url": "https://x/a.png"}],
    )
    assert verdict.passed


def test_a_promised_stimulus_with_no_passage_is_refused() -> None:
    verdict = judge(
        text="Using the information below, choose the correct answer.",
        option_ids=["A", "B"],
        answer="A",
        has_passage=False,
    )
    assert "promised_stimulus_absent" in verdict.reasons


def test_a_promised_stimulus_with_a_passage_passes() -> None:
    verdict = judge(
        text="Using the information below, choose the correct answer.",
        option_ids=["A", "B", "C", "D"],
        answer="A",
        exam="jamb",
        has_passage=True,
    )
    assert verdict.passed


def test_a_cloze_stem_is_not_itself_a_reason_to_refuse() -> None:
    """The waec harvester banned every cloze. The jamb one only banned an
    unaccompanied one. This test pins the second behaviour, which is right."""
    verdict = judge(
        text="The study of the cell membrane is best described as ______.",
        option_ids=["A", "B", "C", "D"],
        answer="A",
        has_passage=False,
    )
    assert not any("cloze" in reason for reason in verdict.reasons)


def test_an_unknown_reason_is_a_programming_error_not_a_data_problem() -> None:
    verdict = judge(text="A real stem with words in it", option_ids=["A", "B"], answer="A")
    with pytest.raises(BankError, match="unknown gate reason"):
        verdict.add("looks_dodgy")


def test_refusals_are_ordered_by_how_fundamental_they_are() -> None:
    """A row with no options is reported as having no options."""
    verdict = judge(text="A.", option_ids=[], answer="Z")
    assert verdict.reason == "few_options"


async def test_the_gate_records_its_verdict(
    store: Any,
    with_question: Repository,
    config: Config,
) -> None:
    result = await run_task(MechanicalGate(), config, with_question, where="all")
    assert result.run.succeeded == 1
    row = (await with_question.rows("questions"))[0]
    assert row["gate_status"] == "pass"
    assert row["gate_reason"] is None


async def test_a_dry_run_writes_nothing(
    store: Any,
    with_question: Repository,
    config: Config,
) -> None:
    await run_task(MechanicalGate(), config, with_question, where="all", dry_run=True)
    row = (await with_question.rows("questions"))[0]
    assert row["gate_status"] == "pending"


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def test_slugify_folds_accents_instead_of_dropping_them() -> None:
    """The old normaliser turned Économie into conomie."""
    assert slugify("Économie") == "economie"
    assert slugify("Poincaré") == "poincare"


def test_slugify_is_stable_for_a_catalog_key() -> None:
    assert slugify("Use of English") == "use-of-english"
    assert slugify("  Data   Processing  ") == "data-processing"


def test_a_double_escaped_entity_survives_one_pass() -> None:
    """The two harvesters decoded this differently, which is why a question's
    text depended on which one had seen it."""
    text, _ = clean_inline("a &amp;amp; b")
    assert text == "a &amp; b"


def test_inline_markup_becomes_text_and_marks() -> None:
    text, marks = clean_inline("the <u>rate</u> doubles")
    assert text == "the rate doubles"
    assert len(marks) == 1
    assert marks[0].kind == "underline"
    assert marks[0].start == 4
    assert marks[0].len == 4


def test_an_image_mark_carries_its_url() -> None:
    _, marks = clean_inline('see <img src="https://x/fig.png" alt="a">')
    assert any(m.kind == "image" and m.url == "https://x/fig.png" for m in marks)


def test_an_image_mark_without_a_url_is_refused() -> None:
    """A figure a candidate cannot see is worse than no mark at all."""
    with pytest.raises(ValueError, match="must carry the url"):
        Mark(kind="image", start=0, len=1)


def test_a_mark_running_past_the_text_is_refused() -> None:
    with pytest.raises(ValueError, match="but the text is"):
        RichText(text="short", inline=[Mark(kind="underline", start=3, len=40)])


def test_overlapping_underlines_are_refused() -> None:
    with pytest.raises(ValueError, match="overlap"):
        RichText(
            text="one two three",
            inline=[
                Mark(kind="underline", start=0, len=6),
                Mark(kind="underline", start=4, len=4),
            ],
        )


def test_merging_text_does_not_glue_words() -> None:
    """What isthefunction was in the bank more than once."""
    assert merge_words(["what is", "the", "function"]) == "what is the function"


def test_page_furniture_is_dropped() -> None:
    lines = visible_lines("<p>Real question text</p><p>Advertisement</p><div>© mySchool.ng</div>")
    assert "Real question text" in lines
    assert not any("Advertisement" in line for line in lines)
    assert not any("mySchool" in line for line in lines)


def test_figure_detection_agrees_with_itself() -> None:
    for text in (
        "as shown in the diagram below",
        "Figure 2 shows the arrangement",
        "refer to the table below",
        "the stave above",
    ):
        assert mentions_figure(text), text
    for text in ("Which of these is true?", "A real stem with words in it."):
        assert not mentions_figure(text), text


def test_a_stimulus_promise_is_detected() -> None:
    assert promises_stimulus("Using the information below, choose one")
    assert not promises_stimulus("Which of the following is a noble gas?")


def test_strip_tags_collapses_whitespace() -> None:
    assert strip_tags("<p>one</p><p>two</p>") == "one two"


# ---------------------------------------------------------------------------
# Snapping a model's offsets back onto the words
# ---------------------------------------------------------------------------


def test_snapping_slides_a_mark_to_a_word_boundary() -> None:
    marks = [Mark(kind="underline", start=5, len=3)]
    snapped = snap_offsets("the rate doubles", marks)
    assert snapped[0].start == 4
    assert "rate" in "the rate doubles"[snapped[0].start : snapped[0].end]


def test_a_stated_phrase_beats_the_models_arithmetic() -> None:
    """The model said rate and got 5..8. We take its word for where it is."""
    marks = [Mark(kind="underline", start=5, len=3)]
    snapped = snap_offsets("the rate of decay", marks, finder="rate of decay")
    assert "rate of decay" in "the rate of decay"[snapped[0].start : snapped[0].end]


def test_a_mark_that_cannot_be_repaired_is_dropped() -> None:
    assert snap_offsets("", [Mark(kind="underline", start=0, len=3)]) == []


# ---------------------------------------------------------------------------
# The task base
# ---------------------------------------------------------------------------


async def test_a_task_that_raises_fails_its_row_not_the_run(
    store: Any,
    with_question: Repository,
    config: Config,
) -> None:
    """One bad question must not stop 199 good ones."""

    class Exploding:
        name = "exploding"
        produces = "nothing"
        requires: tuple[str, ...] = ()
        may_write_ready = False
        iterates_rows = True
        description = "raises on every row"

        async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
            raise RuntimeError("boom")

        async def collect(self, ctx: TaskContext) -> list[RowOutcome]:
            return []

    result = await run_task(Exploding(), config, with_question, where="all")
    assert result.run.failed == 1
    assert result.run.succeeded == 0
    assert result.exit_code == 1


async def test_a_failure_schedules_a_retry_and_is_recorded(
    store: Any,
    with_question: Repository,
    config: Config,
) -> None:
    class Failing:
        name = "failing"
        produces = "nothing"
        requires: tuple[str, ...] = ()
        may_write_ready = False
        iterates_rows = True
        description = "fails retryably"

        async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
            return ctx.fail(str(row["id"]), "transient", "try again", retryable=True)

        async def collect(self, ctx: TaskContext) -> list[RowOutcome]:
            return []

    await run_task(Failing(), config, with_question, where="all")
    row = (await with_question.rows("questions"))[0]
    assert row["error"] is not None
    assert row["next_retry_at"] is not None


async def test_on_error_stop_halts_after_the_first_failure(
    store: Any,
    make_rows: Any,
    config: Config,
) -> None:
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", make_rows(5))

    class AlwaysFails:
        name = "always-fails"
        produces = "nothing"
        requires: tuple[str, ...] = ()
        may_write_ready = False
        iterates_rows = True
        description = "fails on every row"

        async def apply(self, row: dict[str, Any], ctx: TaskContext) -> RowOutcome:
            return ctx.fail(str(row["id"]), "broken", "no")

        async def collect(self, ctx: TaskContext) -> list[RowOutcome]:
            return []

    stopped = config.model_copy(update={"on_error": "stop"})
    result = await run_task(AlwaysFails(), stopped, repo, where="all")
    assert result.run.status == "stopped"
    assert result.run.total < 5


async def test_a_gate_refusal_is_a_skip_not_a_failure(
    store: Any,
    make_rows: Any,
    config: Config,
) -> None:
    """A refused row is expected work, so it must not read as a broken run."""
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", make_rows(3, text="A.", options="[]"))
    result = await run_task(MechanicalGate(), config, repo, where="all")
    assert result.run.skipped == 3
    assert result.run.failed == 0
    assert result.exit_code == 0


async def test_a_limit_bounds_the_run(
    store: Any,
    make_rows: Any,
    config: Config,
) -> None:
    repo = Repository(store, lane="work")
    await repo.insert_many("questions", make_rows(10))
    result = await run_task(MechanicalGate(), config, repo, where="all", limit=3)
    assert result.run.total == 3


def test_the_exit_code_reports_a_broken_run_separately() -> None:
    from utmelab_bank.model.run import Run

    done = TaskResult(run=Run(id="r1", task="t", status="done"))
    assert done.exit_code == 0
    with_failures = TaskResult(run=Run(id="r1", task="t", failed=1))
    assert with_failures.exit_code == 1
    broken = TaskResult(run=Run(id="r1", task="t", status="broken"))
    assert broken.exit_code == 2


def test_a_summary_a_person_can_read() -> None:
    from utmelab_bank.model.run import Run

    run = Run(id="r1", task="tag", target="work", succeeded=187, skipped=13)
    assert TaskResult(run=run).summary() == "tag on work: 187 ok, 13 skipped, 0 failed"


def test_a_refusal_names_the_step_that_is_missing(config: Config) -> None:
    from utmelab_bank.model.run import Run

    ctx = TaskContext(
        config=config, repo=Repository.__new__(Repository), run=Run(id="r1", task="t")
    )
    outcome = ctx.refuse("q1", "ai-describe")
    assert outcome.state == "skipped"
    assert "ai-describe" in str(outcome.detail)
