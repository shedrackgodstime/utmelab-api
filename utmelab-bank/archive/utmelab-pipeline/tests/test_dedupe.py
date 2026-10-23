"""Tests for stem canonicalization and deduplication."""

from pipeline.gates.dedupe import compute_fingerprint


def test_fingerprint_strips_html():
    raw_1 = "<p>What is the <b>SI unit</b> of force?</p>"
    raw_2 = "What is the SI unit of force?"
    assert compute_fingerprint(raw_1) == compute_fingerprint(raw_2)


def test_fingerprint_normalizes_whitespace():
    raw_1 = "Calculate   the   velocity \n of a falling body."
    raw_2 = "Calculate the velocity of a falling body."
    assert compute_fingerprint(raw_1) == compute_fingerprint(raw_2)


def test_fingerprint_case_insensitive():
    raw_1 = "Which OF THE FOLLOWING IS AN ALKALI METAL?"
    raw_2 = "Which of the following is an alkali metal?"
    assert compute_fingerprint(raw_1) == compute_fingerprint(raw_2)


def test_fingerprint_different_stems():
    fp1 = compute_fingerprint("What is the capital of Nigeria?")
    fp2 = compute_fingerprint("What is the capital of Ghana?")
    assert fp1 != fp2
