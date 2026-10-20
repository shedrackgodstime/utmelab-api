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

import pytest

from utmelab_bank.blob.gitstore import GitStore
from utmelab_bank.blob.paths import name_for
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
    assert saved_media["media_url"] == target == name_for(digest, ".png")

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
    """A push that fails for a reason that might clear is a retryable row."""
    bare = _remote(tmp_path)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text('#!/bin/sh\necho "declined" >&2\nexit 1\n', encoding="utf-8")
    hook.chmod(0o755)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"unpushable bytes", ".png")
    media = _media_row("q_1", digest, blob_path, clone.root, row_id="m_push.png", verdict="pass")
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.failed == 1
    assert result.outcomes[0].code == "push_failed"
    assert result.outcomes[0].retryable is True
    saved = (await repo.rows("media", "id=m_push.png"))[0]
    assert saved["status"] == "fetched"


def _git_env_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Take away every way git could learn an identity.

    ``GIT_CONFIG_GLOBAL`` and ``GIT_CONFIG_SYSTEM`` point at paths that do not
    exist, so this machine's ``~/.gitconfig`` cannot quietly satisfy the commit
    and make the test below pass for the wrong reason.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "no-system"))
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)


async def test_a_run_with_no_git_identity_does_not_claim_a_publication(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production incident, at the layer that wrote the rows.

    On 2026-10-19 a runner with no ``user.email`` published two figures as far
    as the database was concerned. ``git commit`` exited 128, the error went to
    stderr where nothing read it, the guard looked for "nothing to commit" in an
    empty stdout and did not find it, and the method returned the previous
    commit's sha. The push then had nothing to send, said "Everything
    up-to-date", and exited zero.

    This asserts the whole chain from the outside: the row's status, the url on
    the question, and a fresh clone of the remote.
    """
    _git_env_off(monkeypatch, tmp_path)
    bare = _remote(tmp_path)
    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")

    question = make_rows(
        1,
        marks=[Mark(kind="image", start=0, len=0, url=SOURCE, position="above")],
    )[0]
    await repo.insert_many("questions", [question])

    clone = _clone(run_config)
    # Strip the identity the helper set, so this is the runner we are modelling.
    _git_env_off(monkeypatch, tmp_path)
    _git(clone.root, "config", "--unset", "user.name")
    _git(clone.root, "config", "--unset", "user.email")

    digest, blob_path, _ = clone.write_blob(b"figure bytes", ".png")
    media = _media_row(question["id"], digest, blob_path, clone.root, verdict="pass")
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.failed == 1, "a run that published nothing cannot be green"
    assert result.exit_code != 0

    saved = (await repo.rows("media", "id=m_figure.png"))[0]
    assert saved["status"] == "fetched", "the row must not claim to be uploaded"
    assert saved["media_url"] == SOURCE, "the question must keep the provider's url"

    marks = json.loads((await repo.rows("questions", f"id={question['id']}"))[0]["inline"])
    assert marks[0]["url"] == SOURCE, "no rewrite without a verified publication"

    # The strongest half: a fresh clone of the remote has no such file, which is
    # exactly what the operator would have found on GitLab.
    verify = tmp_path / "verify"
    _git(tmp_path, "clone", "--branch", "main", str(bare), str(verify))
    assert not (verify / blob_path.relative_to(clone.root)).exists()


async def test_a_green_run_means_a_fresh_clone_has_the_figure(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
) -> None:
    """The other half of the contract, and the only one that matters.

    A green run has to mean the bytes are somewhere anyone else can get them.
    This asserts that against a clone that shares nothing with the run: not the
    working tree, not the index, not the database.
    """
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
    media = _media_row(question["id"], digest, blob_path, clone.root, verdict="pass")
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )
    assert result.run.succeeded == 1
    assert result.run.failed == 0

    verify = tmp_path / "verify"
    _git(tmp_path, "clone", "--branch", "main", str(bare), str(verify))
    landed = verify / blob_path.relative_to(clone.root)
    assert landed.is_file(), "green said published, and the remote disagrees"
    assert landed.read_bytes() == b"figure bytes"

    saved = (await repo.rows("media", "id=m_figure.png"))[0]
    assert saved["status"] == "uploaded"
    assert saved["media_url"] == target
    marks = json.loads((await repo.rows("questions", f"id={question['id']}"))[0]["inline"])
    assert marks[0]["url"] == target


async def test_an_auth_failure_is_not_left_retrying_forever(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
) -> None:
    """A rejected credential must be refused, not scheduled for another try.

    The row still says why, so the operator knows to fix the token, but it is
    not marked retryable: the next attempt would fail identically.
    """
    bare = _remote(tmp_path)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text(
        '#!/bin/sh\necho "remote: HTTP Basic: Access denied." >&2\nexit 1\n', encoding="utf-8"
    )
    hook.chmod(0o755)

    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    question = make_rows(1)[0]
    await repo.insert_many("questions", [question])
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"figure bytes", ".png")
    media = _media_row(question["id"], digest, blob_path, clone.root, verdict="pass")
    await repo.insert_many("media", [media])

    result = await run_task(
        MediaUpload(), run_config, repo, logical="media", where="description verified"
    )

    assert result.run.failed == 1
    assert result.outcomes[0].code == "git_auth_failed"
    assert result.outcomes[0].retryable is False
    assert "access denied" in result.outcomes[0].detail.lower()
    saved = (await repo.rows("media", "id=m_figure.png"))[0]
    assert saved["status"] == "fetched"


async def test_a_push_that_never_lands_leaves_no_row_looking_uploaded(
    store: Store,
    config: Config,
    make_rows: Any,
    tmp_path: Path,
) -> None:
    """The self-sealing failure, closed.

    ``not uploaded`` selects ``status <> 'uploaded'``, so a row wrongly marked
    uploaded is never selected again and nothing ever repairs it. This is the
    test that says a run either puts the bytes there or changes nothing.
    """
    bare = _remote(tmp_path)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text('#!/bin/sh\necho "declined" >&2\nexit 1\n', encoding="utf-8")
    hook.chmod(0o755)

    run_config = _config(config, tmp_path, bare)
    repo = Repository(store, lane="work")
    question = make_rows(1)[0]
    await repo.insert_many("questions", [question])
    clone = _clone(run_config)
    digest, blob_path, _ = clone.write_blob(b"figure bytes", ".png")
    media = _media_row(question["id"], digest, blob_path, clone.root, verdict="pass")
    await repo.insert_many("media", [media])

    await run_task(MediaUpload(), run_config, repo, logical="media", where="description verified")

    assert await repo.count("media", "not uploaded") == 1, (
        "the row must still be selected by the next run"
    )
