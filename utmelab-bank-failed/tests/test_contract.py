"""The API boundary.

These tests read the real ``src/store/schema.rs``, so if the API changes a shape
the tests fail here rather than in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utmelab_bank.contract import load_contract, parse_schema_rs
from utmelab_bank.contract.check import ShapeReport, check_shapes, read_contract_version
from utmelab_bank.contract.content_hash import check_vectors, content_hash, load_vectors
from utmelab_bank.contract.rust_schema import RustContract
from utmelab_bank.contract.version import SUPPORTED_CONTRACT_VERSIONS, refuse_unknown, supported
from utmelab_bank.errors import ContractError
from utmelab_bank.store.client import Store
from utmelab_bank.store.schema import ensure_schema


def test_the_live_schema_file_gives_us_a_contract(rust_schema_path: Path) -> None:
    contract = load_contract(rust_schema_path)
    assert contract.contract_version in SUPPORTED_CONTRACT_VERSIONS
    assert len(contract.read_shapes) >= 20


def test_both_rust_formats_parse(rust_schema_path: Path) -> None:
    """rustfmt puts a short entry on one line and a long one across forty."""
    contract = load_contract(rust_schema_path)
    short = contract.shape_for("countries")
    long = contract.shape_for("questions")
    assert short is not None and short.columns == ()
    assert long is not None and "content_hash" in long.columns


def test_a_missing_version_is_a_refusal() -> None:
    contract = RustContract(1, (), Path("x"))
    with pytest.raises(ContractError, match="no contract version"):
        refuse_unknown(None, contract)


def test_an_unknown_version_is_a_refusal() -> None:
    contract = RustContract(1, (), Path("x"))
    with pytest.raises(ContractError, match="not one we implement"):
        refuse_unknown(99, contract)


def test_a_known_version_passes() -> None:
    contract = RustContract(1, (), Path("x"))
    for version in SUPPORTED_CONTRACT_VERSIONS:
        refuse_unknown(version, contract)
        assert supported(version)


def test_a_parser_that_finds_nothing_refuses(tmp_path: Path) -> None:
    """A partial parse would let every later check pass vacuously."""
    empty = tmp_path / "schema.rs"
    empty.write_text("pub const SOMETHING_ELSE: u64 = 1;", encoding="utf-8")
    with pytest.raises(ContractError):
        parse_schema_rs(empty.read_text(encoding="utf-8"), empty)


def test_missing_from_names_only_what_is_absent() -> None:
    contract = load_contract(Path(__file__).resolve().parents[2] / "src" / "store" / "schema.rs")
    shape = contract.shape_for("questions")
    assert shape is not None
    assert shape.missing_from(frozenset(shape.columns)) == []
    assert "content_hash" in shape.missing_from(frozenset({"id", "exam"}))
    assert "exam" not in shape.missing_from(frozenset({"id", "exam"}))


async def test_a_missing_table_is_named(store: Store, rust_schema_path: Path) -> None:
    from utmelab_bank.contract.rust_schema import ReadShape

    report = await check_shapes(
        store,
        load_contract(rust_schema_path),
        shapes=(ReadShape("no_such_table", ("id",)),),
    )
    assert report.missing_tables == ("no_such_table",)
    assert report.reason() == "table missing: no_such_table"
    assert not report.ok


async def test_the_version_is_none_until_something_stamps_it(store: Store) -> None:
    assert await read_contract_version(store) is None


async def test_reading_the_version_the_api_stamped(store: Store) -> None:
    """We read the API's stamp. We never write it: ``meta`` is their table."""
    await store.set_meta("contract_version", "1")
    assert await read_contract_version(store) == 1


async def test_an_unstamped_version_is_none_not_zero(store: Store) -> None:
    assert await read_contract_version(store) is None


async def test_the_report_says_what_is_wrong(store: Store) -> None:
    """A report that only says 'failed' is a support ticket, not a check."""
    from utmelab_bank.contract.rust_schema import ReadShape

    report = await check_shapes(
        store,
        load_contract(Path(__file__).resolve().parents[2] / "src" / "store" / "schema.rs"),
        shapes=(ReadShape("work_questions", ("id", "not_a_column")),),
    )
    assert "work_questions.not_a_column" in report.missing_columns
    assert report.reason() == "column missing: work_questions.not_a_column"
    assert not report.ok


async def test_a_bank_database_passes_the_bank_shapes(store: Store) -> None:
    """Our own lane tables must satisfy the columns we claim to read."""
    from utmelab_bank.contract.rust_schema import ReadShape

    await ensure_schema(store)
    shape = ReadShape(
        "work_questions",
        ("id", "exam", "subject", "text", "options", "answer", "content_hash", "section"),
    )
    report = await check_shapes(store, load_contract(_schema()), shapes=(shape,))
    assert report.missing_tables == ()
    assert report.missing_columns == ()


def _schema() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "store" / "schema.rs"


def test_an_empty_report_passes() -> None:
    assert ShapeReport(checked_tables=4).ok
    assert ShapeReport(checked_tables=4).reason() is None


# ---------------------------------------------------------------------------
# The content hash, which is the field the api joins on.
# ---------------------------------------------------------------------------


def test_the_content_hash_is_stable_against_the_vectors() -> None:
    """If this fails the whole bank needs re-hashing, so it is not a small edit."""
    cases = load_vectors()
    drifted = check_vectors(cases)
    assert not drifted, f"content hash moved for: {drifted}"


def test_the_hash_is_64_hex() -> None:
    digest = content_hash(
        stem={"text": "hello", "inline": []},
        options=[{"id": "A", "text": {"text": "world", "inline": []}}],
        answer_id="A",
    )
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_a_different_answer_is_a_different_hash() -> None:
    base = {"text": "same stem", "inline": []}
    options = [{"id": "A", "text": {"text": "same", "inline": []}}]
    assert content_hash(stem=base, options=options, answer_id="A") != content_hash(
        stem=base, options=options, answer_id="B"
    )


def test_an_underline_changes_the_hash() -> None:
    """Presentation is part of what a candidate sees, so it is part of identity."""
    plain = content_hash(stem={"text": "abc", "inline": []}, options=[], answer_id="A")
    marked = content_hash(
        stem={
            "text": "abc",
            "inline": [{"kind": "underline", "start": 0, "len": 3}],
        },
        options=[],
        answer_id="A",
    )
    assert plain != marked


def test_no_explanation_and_an_explanation_hash_differently() -> None:
    """The reference emits one empty part with no explanation and two with an
    empty trap, so the two are different digests. An earlier version of this
    file asserted they were equal, and was wrong."""
    with_none = content_hash(stem={"text": "s"}, options=[], answer_id="A", explanation=None)
    with_empty = content_hash(
        stem={"text": "s"},
        options=[],
        answer_id="A",
        explanation={"key_point": {"text": ""}, "body": {"text": ""}, "trap": {"text": ""}},
    )
    assert with_none != with_empty


def test_the_bank_s_own_hashes_are_reproduced() -> None:
    """The vectors are digests read out of the committed bank, so a change in
    part order fails here rather than silently orphaning 2190 verifications."""
    cases = load_vectors()
    assert cases, "no vectors"
    assert all(case.get("from_the_bank") for case in cases), "a vector was not taken from the bank"
    assert all(case.get("matches_stored_hash") for case in cases)
    assert check_vectors(cases) == []
