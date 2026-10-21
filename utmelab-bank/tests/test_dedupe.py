"""Dedupe. Two fingerprints, because there are two kinds of duplicate."""

import pytest

from utmelab_bank.domain.dedupe import Duplicate, near_duplicate_fingerprint


def test_the_fingerprint_ignores_the_case() -> None:
    first = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))
    second = near_duplicate_fingerprint("what is 2 + 2?", ("3", "4", "5", "6"))

    assert first == second


def test_the_fingerprint_ignores_the_option_order() -> None:
    first = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))
    second = near_duplicate_fingerprint("What is 2 + 2?", ("6", "5", "4", "3"))

    assert first == second


def test_the_fingerprint_ignores_surrounding_space() -> None:
    first = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))
    second = near_duplicate_fingerprint("  What is 2 + 2?  ", (" 3 ", "4", "5", "6"))

    assert first == second


def test_a_rewritten_stem_is_not_caught() -> None:
    """The rule is not a similarity measure and does not pretend to be.

    The stem is part of the key, so a stem that was rewritten is a different
    fingerprint. What the rule catches is the same question presented
    differently, and a rewritten stem is a different question.
    """
    first = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))
    second = near_duplicate_fingerprint("What is 2 plus 2?", ("3", "4", "5", "6"))

    assert first != second


def test_a_reworded_option_is_not_caught() -> None:
    """The options are part of the key too."""
    first = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))
    second = near_duplicate_fingerprint("What is 2 + 2?", ("three", "4", "5", "6"))

    assert first != second


def test_a_shuffled_option_set_is_caught() -> None:
    """This is the duplicate that actually happens: the same question
    harvested twice with the answers in a different order."""
    first = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))
    second = near_duplicate_fingerprint("What is 2 + 2?", ("6", "5", "4", "3"))

    assert first == second


def test_different_options_are_a_different_fingerprint() -> None:
    first = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))
    second = near_duplicate_fingerprint("What is 2 + 2?", ("7", "8", "9", "10"))

    assert first != second


def test_the_fingerprint_is_sixteen_hex_characters() -> None:
    fingerprint = near_duplicate_fingerprint("What is 2 + 2?", ("3", "4", "5", "6"))

    assert len(fingerprint) == 16
    assert set(fingerprint) <= set("0123456789abcdef")


def test_a_duplicate_knows_its_kind() -> None:
    exact = Duplicate(kind="exact", question_id="q1")
    near = Duplicate(kind="near", question_id="q2")

    assert exact.kind == "exact"
    assert near.kind == "near"
    assert exact.question_id == "q1"


def test_an_unknown_duplicate_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown duplicate kind"):
        Duplicate(kind="maybe", question_id="q1")
