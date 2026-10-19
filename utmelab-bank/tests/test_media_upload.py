"""media-upload: publish the bytes, then point the question at our copy.

The offline proof uses a real bare git remote and a real clone, because the
thing being tested is the handoff between three places: the clone on disk, the
remote, and the question row's json. A mock git would prove none of them.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from utmelab_bank.blob.gitstore import GitStore
from utmelab_bank.blob.paths import url_for
from utmelab_bank.config import Config, RepoRoot
from utmelab_bank.model.base import now_iso
from utmelab_bank.model.richtext import Mark
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task.base import run_task
from utmelab_bank.task.media.upload import MediaUpload

SOURCE = "https://cdn.example/figure.png"
FAILED_SOURCE = "https://cdn.example/unexplained.png"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _remote(tmp_path: Path) -> Path:
    """A bare remote with a seed commit on ``main``."""
    bare = tmp_path / "media.git"
    _git(tmp_path, "init", "--bare", str(bare))

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.name", "test")
    _git(seed, "config", "user.email", "test@test")
    (seed / "README").write_text("media\n", encoding="utf-8")
    _git(seed, "add", "--all")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "origin", "main")
    return bare


def _config(config: Config, tmp_path: Path, remote: Path, *, enabled: bool = True) -> Config:
    return config.model_copy(
        update={
            "repo": RepoRoot(path=tmp_path / "root"),
            "media_remote": str(remote),
            "media_upload_enabled": enabled,
        }
    )


def _clone(config: Config) -> GitStore:
    store = GitStore(
        root=config.repo.media_repo,
        remote=config.media_remote,
        branch=config.media_branch,
    )
    store.ensure_cloned()
    _git(config.repo.media_repo, "config", "user.name", "test")
    _git(config.repo.media_repo, "config", "user.email", "test@test")
    return store


def _media_row(
    question_id: str,
    digest: str,
    blob_path: Path,
    root: Path,
    *,
    row_id: str = "m_figure.png",
    source: str = SOURCE,
    verdict: str | None = None,
) -> dict[str, Any]:
    stamp = now_iso()
    return {
        "id": row_id,
        "source_url": source,
        "question_id": question_id,
        "blob_path": str(blob_path.relative_to(root)),
        "sha256": digest,
        "bytes": blob_path.stat().st_size,
        "media_url": source,
        "status": "fetched",
        "description": "a figure",
        "description_model": "mock",
        "description_verdict": verdict,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": None,
        "created_at": stamp,
        "updated_at": stamp,
    }


async def test_upload_pushes_the_blob_and_rewrites_the_question(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
) -> None:
    """One push, then the question carries our path and keeps its identity."""
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")

    question = make_rows(
        1,
        marks=[Mark(kind="image", start=0, len=0, url=SOURCE, position="above")],
    )[0]
    await repo.insert_many("questions", [question])

    clone = _clone(run_config)
    digest, blob_path, target = clone.write_blob(b"figure bytes", ".png")
    media = _media_row(question["id"], digest, blob_path, clone.root)
    await repo.insert_many("media", [media])

    result = await run_task(MediaUpload(), run_config, repo, logical="media")

    assert result.exit_code == 0
    assert result.run.succeeded == 1

    saved_media = (await repo.rows("media", "id=m_figure.png"))[0]
    assert saved_media["status"] == "uploaded"
    assert saved_media["media_url"] == target == url_for(digest, ".png")

    saved_question = (await repo.rows("questions", f"id={question['id']}"))[0]
    marks = json.loads(saved_question["inline"])
    assert marks[0]["url"] == target
    assert saved_question["content_hash"] == question["content_hash"], (
        "the identity hash must survive an address change"
    )

    verify = tmp_path / "verify"
    _git(tmp_path, "clone", "--branch", "main", str(bare), str(verify))
    assert (verify / blob_path.relative_to(clone.root)).is_file()


async def test_upload_refuses_to_claim_a_push_it_did_not_make(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
) -> None:
    """With the flag closed, rows skip and nothing is written."""
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare, enabled=False)
    repo = Repository(store, lane="work")
    question = make_rows(1)[0]
    await repo.insert_many("questions", [question])

    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"figure bytes", ".png")
    media = _media_row(question["id"], digest, blob_path, clone.root)
    await repo.insert_many("media", [media])

    result = await run_task(MediaUpload(), run_config, repo, logical="media")

    assert result.run.skipped == 1
    assert result.outcomes[0].code == "push_disabled"
    saved = (await repo.rows("media", "id=m_figure.png"))[0]
    assert saved["status"] == "fetched"
    assert saved["media_url"] == SOURCE


async def test_upload_fails_a_row_whose_bytes_are_gone(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
) -> None:
    """A row that claims a blob but has no file is a failure, not a publish."""
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    question = make_rows(1)[0]
    await repo.insert_many("questions", [question])

    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"figure bytes", ".png")
    media = _media_row(question["id"], digest, blob_path, clone.root)
    blob_path.unlink()
    await repo.insert_many("media", [media])

    result = await run_task(MediaUpload(), run_config, repo, logical="media")

    assert result.run.failed == 1
    assert result.outcomes[0].code == "blob_missing"
    saved = (await repo.rows("media", "id=m_figure.png"))[0]
    assert saved["status"] == "fetched"


async def test_the_default_flow_leaves_an_unverified_figure_on_its_source(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
) -> None:
    """A figure whose description failed keeps the provider's full url.

    That is the fail-closed half of the media rule: we publish our own copy only
    for a figure whose description survived the check. The question with both
    figures shows the split in one row.
    """
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")

    question = make_rows(
        1,
        marks=[
            Mark(kind="image", start=0, len=0, url=SOURCE, position="above"),
            Mark(kind="image", start=0, len=0, url=FAILED_SOURCE, position="below"),
        ],
    )[0]
    await repo.insert_many("questions", [question])

    clone = _clone(run_config)
    pass_digest, pass_blob, pass_target = clone.write_blob(b"explained bytes", ".png")
    fail_digest, fail_blob, _ = clone.write_blob(b"unexplained bytes", ".png")
    await repo.insert_many(
        "media",
        [
            _media_row(
                question["id"],
                pass_digest,
                pass_blob,
                clone.root,
                row_id="m_pass.png",
                verdict="pass",
            ),
            _media_row(
                question["id"],
                fail_digest,
                fail_blob,
                clone.root,
                row_id="m_fail.png",
                source=FAILED_SOURCE,
                verdict="fail",
            ),
        ],
    )

    result = await run_task(
        MediaUpload(),
        run_config,
        repo,
        logical="media",
        where="description verified",
    )

    assert result.run.succeeded == 1
    saved_pass = (await repo.rows("media", "id=m_pass.png"))[0]
    saved_fail = (await repo.rows("media", "id=m_fail.png"))[0]
    assert saved_pass["status"] == "uploaded"
    assert saved_fail["status"] == "fetched"
    assert saved_fail["media_url"] == FAILED_SOURCE

    marks = json.loads((await repo.rows("questions", f"id={question['id']}"))[0]["inline"])
    assert [mark["url"] for mark in marks] == [pass_target, FAILED_SOURCE]


async def test_a_dry_run_never_touches_the_remote(
    store: Store,
    config: Config,
    make_rows: Any,
    media_rows: list[dict[str, Any]],
) -> None:
    repo = Repository(store, lane="work")
    question = make_rows(1)[0]
    await repo.insert_many("questions", [question])

    row = media_rows[0]
    row.update(
        {
            "id": "m_dry.png",
            "question_id": question["id"],
            "blob_path": "media/aa/example.png",
            "sha256": "a" * 64,
            "media_url": SOURCE,
            "status": "fetched",
        }
    )
    await repo.insert_many("media", [row])

    result = await run_task(MediaUpload(), config, repo, logical="media", dry_run=True)

    assert result.run.succeeded == 1
    saved = (await repo.rows("media", "id=m_dry.png"))[0]
    assert saved["status"] == "fetched"
    assert saved["media_url"] == SOURCE


async def test_upload_fails_a_row_with_no_question(
    store: Store,
    config: Config,
    tmp_path: Path,
) -> None:
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"orphan bytes", ".png")
    media = _media_row("", digest, blob_path, clone.root, row_id="m_orphan.png", verdict="pass")
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.failed == 1
    assert result.outcomes[0].code == "no_question"
    saved = (await repo.rows("media", "id=m_orphan.png"))[0]
    assert saved["status"] == "fetched"


async def test_upload_fails_a_row_whose_question_is_not_in_the_lane(
    store: Store,
    config: Config,
    tmp_path: Path,
) -> None:
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"lost bytes", ".png")
    media = _media_row(
        "q_missing", digest, blob_path, clone.root, row_id="m_lost.png", verdict="pass"
    )
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.failed == 1
    assert result.outcomes[0].code == "question_missing"


async def test_upload_fails_a_row_with_no_usable_address(
    store: Store,
    config: Config,
    tmp_path: Path,
) -> None:
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"unaddressable bytes", ".png")
    media = _media_row("q_1", digest, blob_path, clone.root, row_id="m_bad.png", verdict="pass")
    media["sha256"] = ""
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.failed == 1
    assert result.outcomes[0].code == "bad_address"


async def test_upload_with_the_json_sink_never_touches_git(
    store: Store,
    config: Config,
    tmp_path: Path,
) -> None:
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare).model_copy(update={"sink": "json"})
    repo = Repository(store, lane="work")
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"sink bytes", ".png")
    media = _media_row("q_1", digest, blob_path, clone.root, row_id="m_json.png", verdict="pass")
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.succeeded == 1
    saved = (await repo.rows("media", "id=m_json.png"))[0]
    assert saved["status"] == "fetched"
    assert saved["media_url"] == SOURCE


async def test_a_failed_push_is_a_retryable_row_failure(
    store: Store,
    config: Config,
    tmp_path: Path,
) -> None:
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"unpushable bytes", ".png")
    media = _media_row("q_1", digest, blob_path, clone.root, row_id="m_push.png", verdict="pass")
    await repo.insert_many("media", [media])

    gone = tmp_path / "gone.git"
    bare.rename(gone)

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.failed == 1
    assert result.outcomes[0].code == "push_failed"
    assert result.outcomes[0].retryable is True
    saved = (await repo.rows("media", "id=m_push.png"))[0]
    assert saved["status"] == "fetched"
