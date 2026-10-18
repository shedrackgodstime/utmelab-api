"""media_fetch: each discovered figure's bytes land in the media clone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from utmelab_bank.config import Config, RepoRoot
from utmelab_bank.model.base import now_iso
from utmelab_bank.source.http import PoliteSession
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.store.schema import ensure_schema
from utmelab_bank.task import run_task
from utmelab_bank.task.media import MediaFetch

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


async def fake_get(self, url: str, **kwargs: Any) -> Any:
    """Fake HTTP response returning image bytes."""

    class FakeResponse:
        content = PNG_BYTES
        headers = {"content-type": "image/png"}

    return FakeResponse()


async def failing_get(self, url: str, **kwargs: Any) -> Any:
    """Fake HTTP response that always fails."""
    raise OSError("network down")


@pytest.fixture
def media_config(tmp_path: Path) -> Config:
    """Config with a temp media clone that already exists (ensure_cloned is a no-op)."""
    clone_root = tmp_path / "utmelab-bank" / "var" / "media-repo"
    clone_root.mkdir(parents=True)
    (clone_root / ".git").mkdir()
    return Config(
        repo=RepoRoot(path=tmp_path),
        sink="db",
        lane="work",
        local_database=tmp_path / "bank.db",
        media_remote="https://example.com/media.git",
        media_branch="main",
    )


@pytest.fixture
async def media_store(media_config: Config) -> Store:
    """A temp database with the media lane DDL applied."""
    opened = await Store.open(f"sqlite:{media_config.local_database}")
    await ensure_schema(opened)
    await opened.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    yield opened
    await opened.aclose()


def media_row(**overrides: Any) -> dict[str, Any]:
    """One discovered media row, ready to be fetched."""
    stamp = now_iso()
    row: dict[str, Any] = {
        "id": "m_fig1",
        "source_url": "https://cdn.example/fig-1.png",
        "question_id": "q_1",
        "status": "discovered",
        "blob_path": None,
        "sha256": None,
        "bytes": None,
        "media_url": None,
        "description": None,
        "description_model": None,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": "r_setup",
        "created_at": stamp,
        "updated_at": stamp,
    }
    if overrides:
        row.update(overrides)
    return row


async def test_fetch_downloads_bytes_into_clone(
    media_config: Config, media_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each discovered figure's bytes are written to the clone and the row stamped."""
    monkeypatch.setattr(PoliteSession, "get", fake_get)

    repo = Repository(media_store, lane="work")
    await repo.insert_many("media", [media_row()])

    result = await run_task(MediaFetch(), media_config, repo, logical="media")

    assert result.run.succeeded == 1
    assert result.run.failed == 0

    updated = (await repo.rows("media", "id=m_fig1"))[0]
    assert updated["status"] == "fetched"
    assert updated["sha256"] is not None
    assert len(updated["sha256"]) == 64
    assert updated["bytes"] == len(PNG_BYTES)
    assert updated["media_url"].startswith("/media/")
    assert updated["blob_path"].startswith("media/")
    assert updated["error"] is None
    assert updated["next_retry_at"] is None

    blob_path = Path(media_config.repo.media_repo) / updated["blob_path"]
    assert blob_path.is_file()
    assert blob_path.read_bytes() == PNG_BYTES


async def test_fetch_skips_already_fetched_row(
    media_config: Config, media_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running fetch on an already-fetched row skips without re-downloading."""
    monkeypatch.setattr(PoliteSession, "get", fake_get)

    repo = Repository(media_store, lane="work")
    await repo.insert_many(
        "media",
        [
            media_row(
                id="m_fig2",
                source_url="https://cdn.example/fig-2.jpg",
                status="fetched",
                blob_path="media/ab/" + "a" * 64 + ".jpg",
                sha256="a" * 64,
                bytes=42,
                media_url="/media/ab/" + "a" * 64 + ".jpg",
            )
        ],
    )

    result = await run_task(MediaFetch(), media_config, repo, logical="media")

    assert result.run.skipped == 1
    assert result.run.failed == 0
    updated = (await repo.rows("media", "id=m_fig2"))[0]
    assert updated["status"] == "fetched"


async def test_fetch_failure_is_retryable(
    media_config: Config, media_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Network failures mark the row for retry rather than breaking the run."""
    monkeypatch.setattr(PoliteSession, "get", failing_get)

    repo = Repository(media_store, lane="work")
    await repo.insert_many("media", [media_row()])

    result = await run_task(MediaFetch(), media_config, repo, logical="media")

    assert result.run.failed == 1
    assert result.run.succeeded == 0

    updated = (await repo.rows("media", "id=m_fig1"))[0]
    assert updated["error"] is not None
    assert updated["next_retry_at"] is not None
    assert updated["status"] == "discovered"


async def test_fetch_uses_json_sink_without_writing_files(
    media_config: Config, media_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With --sink json the task succeeds without touching the filesystem."""
    monkeypatch.setattr(PoliteSession, "get", fake_get)

    json_config = media_config.model_copy(update={"sink": "json"})
    repo = Repository(media_store, lane="work")
    await repo.insert_many("media", [media_row()])

    result = await run_task(MediaFetch(), json_config, repo, logical="media")

    assert result.run.succeeded == 1
    assert result.run.failed == 0
    clone_root = media_config.repo.media_repo
    assert not (clone_root / "media").exists()
