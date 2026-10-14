"""Tests for Gate 0 mechanical validation."""

from pipeline.gates.mechanical import validate_gate0


def test_gate0_valid_jamb_question():
    stem = "What is the speed of light in vacuum?"
    options = [
        {"id": "a", "text": "3 x 10^8 m/s"},
        {"id": "b", "text": "3 x 10^6 m/s"},
        {"id": "c", "text": "3 x 10^5 m/s"},
        {"id": "d", "text": "3 x 10^7 m/s"},
    ]
    res = validate_gate0(stem, options, reported_answer="a", exam="JAMB")
    assert res.is_valid is True
    assert res.rejection_reason is None
    assert res.requires_media is False


def test_gate0_rejects_short_stem():
    stem = "Too short"
    options = [
        {"id": "a", "text": "opt a"},
        {"id": "b", "text": "opt b"},
        {"id": "c", "text": "opt c"},
        {"id": "d", "text": "opt d"},
    ]
    res = validate_gate0(stem, options, reported_answer="a")
    assert res.is_valid is False
    assert res.rejection_reason == "stem_too_short"


def test_gate0_rejects_invalid_option_count_jamb():
    stem = "Which gas is evolved when calcium carbonate reacts with dilute HCl?"
    options = [
        {"id": "a", "text": "Carbon dioxide"},
        {"id": "b", "text": "Hydrogen"},
        {"id": "c", "text": "Oxygen"},
    ]
    res = validate_gate0(stem, options, reported_answer="a", exam="JAMB")
    assert res.is_valid is False
    assert "invalid_option_count_jamb_requires_4" in res.rejection_reason


def test_gate0_waec_accepts_5_options():
    stem = "Which of the following elements is a noble gas?"
    options = [
        {"id": "a", "text": "Helium"},
        {"id": "b", "text": "Nitrogen"},
        {"id": "c", "text": "Oxygen"},
        {"id": "d", "text": "Chlorine"},
        {"id": "e", "text": "Fluorine"},
    ]
    res = validate_gate0(stem, options, reported_answer="a", exam="WAEC")
    assert res.is_valid is True


def test_gate0_rejects_missing_answer_in_options():
    stem = "What is the formula of water according to modern chemical nomenclature?"
    options = [
        {"id": "a", "text": "H2O"},
        {"id": "b", "text": "CO2"},
        {"id": "c", "text": "NaCl"},
        {"id": "d", "text": "CH4"},
    ]
    res = validate_gate0(stem, options, reported_answer="z", exam="JAMB")
    assert res.is_valid is False
    assert "not_in_options" in res.rejection_reason


def test_gate0_rejects_missing_diagram_hint():
    stem = "In the circuit diagram shown above, calculate the total resistance across XY."
    options = [
        {"id": "a", "text": "4 ohms"},
        {"id": "b", "text": "8 ohms"},
        {"id": "c", "text": "12 ohms"},
        {"id": "d", "text": "16 ohms"},
    ]
    # No media URL provided
    res = validate_gate0(stem, options, reported_answer="a", exam="JAMB", media_url=None)
    assert res.is_valid is False
    assert res.rejection_reason == "missing_referenced_figure_in_stem"
    assert res.requires_media is True

    # When media URL is provided
    res_ok = validate_gate0(stem, options, reported_answer="a", exam="JAMB", media_url="https://example.com/circuit.png")
    assert res_ok.is_valid is True
    assert res_ok.requires_media is True
