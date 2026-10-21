import pytest

from utmelab_bank.domain.hashing import (
    canonical_json_bytes,
    content_fingerprint,
    payload_hash,
    sha256_hex,
)
from utmelab_bank.domain.models.common import Option, RichText


class StoredExplanation:
    """Only the three fields the fingerprint reads."""

    def __init__(self, key_point: str, body: str, trap: str | None) -> None:
        self.key_point = RichText(text=key_point)
        self.body = RichText(text=body)
        self.trap = RichText(text=trap) if trap is not None else None


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


def test_the_hash_keeps_a_leading_space() -> None:
    """Two real production rows carry a leading space in the explanation.

    ``q_claim_2025_economics_76626`` has one on the body,
    ``q_claim_2025_hausa_75937`` has one on the key point. Both are pinned
    here with the hash production stored, so a strip that creeps back in
    fails the suite instead of only failing in production.
    """
    stem = RichText(text="Cost push inflation is caused by a")
    options = [
        Option(id="a", text=RichText(text="decrease in the cost of production")),
        Option(id="b", text=RichText(text="rise in demand for goods")),
        Option(id="c", text=RichText(text="decrease in the transportation cost")),
        Option(id="d", text=RichText(text="rise in the cost of production")),
    ]
    explanation = StoredExplanation(
        key_point="Cost-push starts at rising costs.",
        body=(
            " dearer inputs push prices up. Cheaper costs, demand rises and "
            "cheaper transport pull or demand."
        ),
        trap="Demand-rise tempts as inflation, but cost-push is supply-side.",
    )

    assert (
        content_fingerprint(
            stem=stem, options=options, answer="d", explanation=explanation
        )
        == "97106b8098f0e78c01a6e041e4a3f040524025c52246b69e7a9b6e0506728cad"
    )


def test_the_hash_keeps_a_leading_space_on_the_key_point() -> None:
    stem = RichText(
        text=(
            "Read the passage and answer questions below. \"Akwai wani yaro mai "
            "suna Umar, wanda ke zaune a garin Funtua. Umar na da sha'awar "
            "karatu sosai, musamman kimiyya. Duk da cewa iyayensa ba su da "
            "karfi, suna dagewa wajen tallafa masa domin cimma burinsa. "
            "Kullum yana zuwa makaranta da wuri, yana kuma taimaka wa "
            "malamansa. Ranar wata gasa ta kimiyya, Umar ya lashe kyauta ta "
            "farko. Wannan ya sa aka yaba masa a makarantar gaba ɗaya.\" Me "
            "Umar ya samu bayan gasar kimiyya?"
        )
    )
    options = [
        Option(id="a", text=RichText(text="Korewa")),
        Option(id="b", text=RichText(text="Sauyawa makaranta")),
        Option(id="c", text=RichText(text="Kyauta")),
        Option(id="d", text=RichText(text="Hukunci")),
    ]
    explanation = StoredExplanation(
        key_point=" contests pay prizes.",
        body=(
            "After the contest: kyauta ta farko. Expulsion, transfer and "
            "punishment miss the win."
        ),
        trap="Transfer tempts as school-move, but the fruit is prize.",
    )

    assert (
        content_fingerprint(
            stem=stem, options=options, answer="c", explanation=explanation
        )
        == "a11038719770d705d2dc8cd145ac50da0a3c939b1b749718480d5c2c9301c264"
    )
