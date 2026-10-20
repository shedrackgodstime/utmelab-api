import pytest

from utmelab_pipeline.domain.hashing import canonical_json_bytes, payload_hash, sha256_hex


def test_json_key_order_is_irrelevant() -> None:
    assert payload_hash({"b": 2, "a": 1}) == payload_hash({"a": 1, "b": 2})


def test_canonical_json_is_compact() -> None:
    assert canonical_json_bytes({"a": 1, "b": [2, 3]}) == b'{"a":1,"b":[2,3]}'


def test_sha256_matches_the_known_empty_digest() -> None:
    assert (
        sha256_hex(b"")
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_payload_hash_is_a_sha256() -> None:
    value = payload_hash({"stem": "What is 2 + 2?"})
    assert len(value) == 64
    assert set(value) <= set("0123456789abcdef")


def test_nan_is_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})
