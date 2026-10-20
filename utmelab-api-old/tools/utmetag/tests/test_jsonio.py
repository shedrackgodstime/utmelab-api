import pytest

from utmetag.jsonio import extract_json


def test_plain_object():
    assert extract_json('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_fenced_json():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_fence_without_language():
    assert extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_prose_wrapped():
    text = 'Sure! Here is the result:\n{"a": 1}\nLet me know if that helps.'
    assert extract_json(text) == {"a": 1}


def test_empty_raises():
    with pytest.raises(ValueError):
        extract_json("   ")


def test_none_raises():
    with pytest.raises(ValueError):
        extract_json(None)


def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("I cannot answer that.")
