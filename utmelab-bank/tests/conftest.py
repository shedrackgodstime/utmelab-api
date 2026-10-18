"""Shared fixtures.

Two ideas carry most of the weight here.

**One in-memory database for every test that touches storage.** It runs the real
lane DDL, so a test cannot pass against a schema the code would not create.

**One bank fixture.** A real question, built once, used by every task test. Tests
that build their own inline question each get subtly different shapes, and then
a failure is a question about the fixture rather than about the code.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from utmelab_bank.config import Config, RepoRoot
from utmelab_bank.model.richtext import Mark, Option, RichText
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.store.schema import ensure_schema

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent


@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test should inherit a developer's environment."""
    for key in list(os.environ):
        if key.startswith("UTMELAB_BANK_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def rust_schema_path() -> Path:
    return REPO_ROOT / "src" / "store" / "schema.rs"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A config pointed at a temporary var directory, so nothing escapes."""
    return Config(
        repo=RepoRoot(path=REPO_ROOT),
        sink="db",
        lane="work",
        local_database=tmp_path / "bank.db",
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    """A temporary database with the real lane DDL applied.

    A file rather than ``:memory:``, because the driver opens a connection per
    operation and an in-memory database does not survive that. Testing against a
    file is also closer to what a run does.

    ``meta`` is created here with the API's own declaration of it, because the
    contract version lives there and that table is the API's to create, not ours.
    """
    opened = await Store.open(f"sqlite:{tmp_path / 'bank.db'}")
    await ensure_schema(opened)
    await opened.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    yield opened
    await opened.aclose()


@pytest.fixture
def repo(store: Store) -> Repository:
    return Repository(store, lane="work")


def make_richtext(text: str, marks: list[Mark] | None = None) -> RichText:
    return RichText(text=text, inline=marks or [])


def make_question(**overrides: Any) -> dict[str, Any]:
    """A question row, as the work lane stores it."""
    import json

    from utmelab_bank.contract.content_hash import content_hash
    from utmelab_bank.model.base import now_iso
    from utmelab_bank.text.richtext import rt_json

    stem = overrides.pop("stem", "Which of the following is a noble gas?")
    options = overrides.pop("options", ["Argon", "Oxygen", "Iron", "Sodium"])
    answer = overrides.pop("answer", "A")
    marks = overrides.pop("marks", [])
    row_id = overrides.pop("id", "q_test_1")

    option_models = [
        Option(id=chr(ord("A") + i), text=RichText(text=t)) for i, t in enumerate(options)
    ]
    digest = content_hash(
        stem=RichText(text=stem, inline=marks),
        options=option_models,
        answer_id=answer,
        explanation=None,
    )
    stamp = now_iso()
    row: dict[str, Any] = {
        "id": row_id,
        # The raw lane's dedupe key is these three together, so each generated
        # row gets its own. Sharing one set across rows was never realistic:
        # two questions from one paper are two urls and two payloads.
        "source_url": f"https://myschool.ng/api/web/v1/classroom/physics?exam_type=jamb#{row_id}",
        "source_item_id": str(row_id),
        "payload_hash": hashlib.sha256(str(row_id).encode()).hexdigest(),
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "source": "claimed_paper",
        "text": stem,
        "inline": rt_json(marks),
        "options": json.dumps(
            [o.model_dump(mode="json") for o in option_models], separators=(",", ":")
        ),
        "answer": answer,
        "subtopic_id": None,
        "section": None,
        "passage_id": None,
        "explanation": None,
        "marks": 1.0,
        "difficulty": 3,
        "content_hash": digest,
        "fingerprint": None,
        "gate_status": "pending",
        "gate_reason": None,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": "r_setup",
        "created_at": stamp,
        "updated_at": stamp,
    }
    row.update(overrides)
    return row


@pytest.fixture
def question_row() -> dict[str, Any]:
    return make_question()


@pytest.fixture
def make_rows():
    """Build a list of distinct questions.

    Spread-copying one row and changing only its id leaves the raw lane's dedupe
    key identical, so twenty five rows collapse to one. Rows are built through
    the factory so the key moves with the id.
    """

    def build(count: int, **overrides: Any) -> list[dict[str, Any]]:
        return [make_question(id=f"q_{index}", **overrides) for index in range(count)]

    return build


@pytest.fixture
async def with_question(repo: Repository, question_row: dict[str, Any]) -> Repository:
    await repo.insert_many("questions", [question_row])
    return repo


@pytest.fixture
def media_rows() -> Iterator[list[dict[str, Any]]]:
    from utmelab_bank.model.base import now_iso

    stamp = now_iso()

    def build(url: str, **overrides: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": f"m_{url.rsplit('/', 1)[-1][:40]}",
            "source_url": url,
            "question_id": None,
            "blob_path": None,
            "derived_path": None,
            "sha256": None,
            "bytes": None,
            "media_url": None,
            "status": "discovered",
            "description": None,
            "description_model": None,
            "attempts": 0,
            "error": None,
            "next_retry_at": None,
            "run_id": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        row.update(overrides)
        return row

    yield [build("https://cdn.example/fig-1.png"), build("https://cdn.example/fig-2.jpg")]
