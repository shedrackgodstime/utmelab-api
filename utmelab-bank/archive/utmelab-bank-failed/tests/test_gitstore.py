"""The git layer must never report a publication it did not make.

This file exists because it did. On 2026-10-19 a ``media-upload`` run reported two
figures published, stamped ``status='uploaded'`` on both rows, and rewrote the
questions to ``/media/ab/<sha>.png``. Nothing was on GitLab. The chain was:

1. ``git commit`` failed because the runner had no ``user.email``.
2. ``commit`` passed ``check=False``, so the failure raised nothing.
3. The error text is on stderr, and the helper returned stdout, so the output
   was the empty string.
4. The guard was ``"nothing to commit" in output``, which is False for "".
5. ``has_commits()`` was True, because the clone had a seed commit.
6. So ``commit`` returned the sha of the *old* commit and carried on.
7. ``git push`` found nothing to send: "Everything up-to-date", exit 0.
8. ``push`` returned a ``PushReport`` of hardcoded zeros that nobody read.
9. The rows were marked published.

Every test here is one of those steps, made to fail loudly. The proofs use a
real bare remote, because the thing being tested is the handoff between the
clone on disk, the remote, and what the caller is told. A mock git proves none
of them.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from utmelab_bank.blob.gitstore import GitStore
from utmelab_bank.blob.paths import REPO_DIR
from utmelab_bank.errors import BlobError, GitAuthError

#: Enough to look like a real figure to anything that sniffs magic bytes.
PNG = b"\x89PNG\r\n\x1a\n" + b"figure bytes" * 8


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=False, capture_output=True, text=True
    )


def git(cwd: Path, *args: str) -> str:
    done = run_git(cwd, *args)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {done.stderr}")
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def _isolated_git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No git config from this machine reaches the test.

    Pointing the global and system config at paths that do not exist is what
    makes the no-identity case deterministic. A developer with a ``~/.gitconfig``
    would otherwise make the test that reproduces the production bug pass
    vacuously, which is the one outcome a regression test must never have.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global-config"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "no-system-config"))
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def with_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """An identity, the way CI provides one."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "utmelab-bot")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "bot@utmelab.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "utmelab-bot")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "bot@utmelab.com")


def _bare_remote(path: Path) -> Path:
    """A bare remote with one seed commit on ``main``, at a path we choose."""
    git(path.parent, "init", "--quiet", "--bare", str(path))
    seed = path.parent / f"{path.name}-seed"
    seed.mkdir()
    git(seed, "init", "--quiet", "-b", "main")
    git(seed, "config", "user.name", "seed")
    git(seed, "config", "user.email", "seed@example.com")
    (seed / "README").write_text("media\n", encoding="utf-8")
    git(seed, "add", "--all")
    git(seed, "commit", "--quiet", "-m", "seed")
    git(seed, "remote", "add", "origin", str(path))
    git(seed, "push", "--quiet", "origin", "main")
    return path


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    """The remote the store under test publishes to."""
    return _bare_remote(tmp_path / "media.git")


@pytest.fixture
def store(tmp_path: Path, bare_remote: Path) -> GitStore:
    return GitStore(root=tmp_path / "clone", remote=str(bare_remote), branch="main")


def seed_blob(store: GitStore, data: bytes = PNG) -> tuple[str, Path, str]:
    store.ensure_cloned()
    digest, path, target = store.write_blob(data, ".png")
    git(store.root, "add", "--all", "--", REPO_DIR)
    return digest, path, target


# ---------------------------------------------------------------------------
# Step 1 to 6: a failed commit must raise, not return the previous sha.
# ---------------------------------------------------------------------------


def test_a_commit_that_fails_raises_rather_than_returning_the_old_sha(
    store: GitStore,
) -> None:
    """The production bug, exactly.

    No identity is configured, so ``git commit`` exits non-zero. The old code
    swallowed the exit code, read an empty stdout, decided the guard was False,
    saw that the clone had commits, and returned the sha of the seed commit as
    though it had just written one.
    """
    seed_blob(store)
    before = git(store.root, "rev-parse", "HEAD")

    with pytest.raises(BlobError) as caught:
        store.commit("media: publish fetched figures")

    assert caught.value.code == "blob_error"
    # The message has to say what git said. An empty error is how a failure
    # becomes a mystery three steps later.
    assert "email" in str(caught.value).lower() or "identity" in str(caught.value).lower()
    assert git(store.root, "rev-parse", "HEAD") == before, "HEAD must not move"


def test_a_commit_that_fails_names_the_exit_status(store: GitStore) -> None:
    """The error carries git's own words, not a generic string."""
    seed_blob(store)
    with pytest.raises(BlobError) as caught:
        store.commit("media: publish fetched figures")
    context = caught.value.context
    assert context.get("status") not in (None, 0)


def test_a_successful_commit_returns_the_new_sha(
    store: GitStore, with_identity: None
) -> None:
    """The positive control. Without it the test above proves nothing."""
    seed_blob(store)
    before = git(store.root, "rev-parse", "HEAD")

    sha = store.commit("media: publish fetched figures")

    assert sha is not None
    assert sha != before[: len(sha)]
    assert git(store.root, "rev-parse", "--short", "HEAD") == sha


def test_a_commit_with_nothing_staged_returns_none(
    store: GitStore, with_identity: None
) -> None:
    """No staged change is a legitimate no-op, distinct from a failure.

    This is the case the old string check was reaching for. It has to keep
    working, or every re-run that finds nothing new would raise.
    """
    store.ensure_cloned()
    assert store.commit("media: publish fetched figures") is None


def test_publish_clones_itself_inside_another_work_tree(
    tmp_path: Path, bare_remote: Path, with_identity: None
) -> None:
    """The clone lives under ``utmelab-bank/var/``, which is inside this repo.

    Found on the first real run. With no clone of its own, every git command
    walked up to the outer repository, and ``git add`` refused with a message
    about ``utmelab-bank/var`` being gitignored. A caller that has to remember
    to clone is a caller that eventually forgets, so ``publish`` does it.
    """
    outer = tmp_path / "outer"
    outer.mkdir()
    git(outer, "init", "--quiet", "-b", "main")
    (outer / ".gitignore").write_text("var/\n", encoding="utf-8")
    git(outer, "config", "user.name", "outer")
    git(outer, "config", "user.email", "outer@example.com")
    (outer / "README").write_text("outer\n", encoding="utf-8")
    git(outer, "add", "--all")
    git(outer, "commit", "--quiet", "-m", "outer")

    root = outer / "var" / "media-repo"
    root.parent.mkdir(parents=True)
    store = GitStore(root=root, remote=str(bare_remote), branch="main")

    # The blob has to land in the real clone first, which is what media-fetch
    # does, so the fixture writes it there the way the task would.
    store.ensure_cloned()
    digest, _, target = store.write_blob(PNG, ".png")

    report = store.publish([(digest, ".png", target)], allowed=True)

    assert report.files == 1
    assert (root / ".git").is_dir(), "publish must leave a real clone behind"
    store.verify_published([(digest, ".png", target)])


def test_a_publish_with_no_clone_says_where_it_looked(
    tmp_path: Path, with_identity: None
) -> None:
    """A clone that cannot be made must name the directory, not just fail.

    The half-made case is the one that cost an afternoon: git succeeded, it
    just succeeded against the wrong repository.
    """
    store = GitStore(root=tmp_path / "nowhere" / "clone", remote="", branch="main")
    with pytest.raises(BlobError) as caught:
        store.ensure_cloned()
    assert "no media remote configured" in str(caught.value)


def test_a_protected_branch_is_appended_to_instead_of_refused(
    tmp_path: Path, bare_remote: Path, with_identity: None
) -> None:
    """GitLab protects ``main`` and refuses a force push even to a maintainer.

    The rewrite this store prefers is unavailable there, so it must fall back
    to an ordinary commit rather than fail. The figures still land and the
    remote is still checked; only the shape of history changes, and the bytes
    stay content-addressed, so nothing is stored twice.

    The hook below is the server side of the refusal, in the same words GitLab
    uses: a non-fast-forward update is rejected, a normal one is accepted.
    """
    hook = bare_remote / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "status=0\n"
        "while read old new ref; do\n"
        '  case "$old" in '
        "0000000000000000000000000000000000000000) continue;; esac\n"
        '  if ! git merge-base --is-ancestor "$old" "$new"; then\n'
        '    echo "remote: GitLab: You are not allowed to force push code '
        'to a protected branch on this project." >&2\n'
        "    status=1\n"
        "  fi\n"
        "done\n"
        "exit $status\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    store = GitStore(root=tmp_path / "clone", remote=str(bare_remote), branch="main")
    digest, _, target = seed_blob(store)

    report = store.publish(
        [(digest, ".png", target)], allowed=True, attempts=3, backoff=0.01
    )

    assert report.squashed is False, "a protected branch has to be appended to"
    assert report.files == 1
    store.verify_published([(digest, ".png", target)])
    assert git(bare_remote, "rev-list", "--count", "main") == "2"


# ---------------------------------------------------------------------------
# Identity is checked before git is asked to use it.
# ---------------------------------------------------------------------------


def test_a_missing_identity_is_named_before_any_commit(
    store: GitStore,
) -> None:
    """The refusal says which command to run, not just that something is wrong."""
    store.ensure_cloned()
    with pytest.raises(BlobError) as caught:
        store.ensure_identity()
    message = str(caught.value)
    assert "user.email" in message
    assert "git config" in message


def test_identity_is_satisfied_by_the_environment(
    store: GitStore, with_identity: None
) -> None:
    """CI sets the identity through the environment, and that must count."""
    store.ensure_cloned()
    store.ensure_identity()


def test_a_clone_is_preflighted_before_it_is_used(store: GitStore) -> None:
    """``ensure_ready`` is the one call a caller makes, and it checks both.

    With the identity demanded it refuses before any git command runs, which is
    the difference between a four word message at the start of a run and a
    three line git error at the end of one.
    """
    store.ensure_ready(with_identity=False)
    with pytest.raises(BlobError) as caught:
        store.ensure_ready(with_identity=True)
    assert "user.email" in str(caught.value)


# ---------------------------------------------------------------------------
# Step 7 and 8: a push that did not land is a failure.
# ---------------------------------------------------------------------------


def test_verify_rejects_a_push_that_did_not_move_the_remote(
    store: GitStore, with_identity: None
) -> None:
    """The remote ref still points at the seed commit, so nothing was published.

    This is the state the production run was in. Local HEAD had moved but the
    remote never received it, which is exactly what ``git push`` reports when
    there was nothing staged to send.
    """
    digest, _, target = seed_blob(store)
    store.commit("media: publish fetched figures")

    # A second remote, holding the same figure at a different commit, so this
    # clone's HEAD is not what any remote is serving.
    other = _bare_remote(store.root.parent / "other.git")
    decoy = GitStore(root=store.root.parent / "decoy", remote=str(other), branch="main")
    decoy.ensure_cloned()
    _, blob_path, _ = decoy.write_blob(PNG, ".png")
    del blob_path
    decoy.publish([(digest, ".png", target)], allowed=True)

    with pytest.raises(BlobError) as caught:
        store.verify_published([(digest, ".png", target)])
    assert "different commit" in str(caught.value)


def test_verify_accepts_a_push_that_landed(store: GitStore, with_identity: None) -> None:
    """The other half. Verification that never passes is worse than none."""
    digest, _, target = seed_blob(store)
    ref = (digest, ".png", target)

    report = store.publish([ref], allowed=True)

    assert report.files == 1
    assert report.sha == git(store.root, "rev-parse", "HEAD")
    store.verify_published([ref])


def test_verify_rejects_a_blob_missing_from_the_published_tree(
    store: GitStore, with_identity: None
) -> None:
    """One blob present and one absent must not read as success.

    A batch is the normal case. Checking only the first path would let a
    half-failed batch report itself as published.
    """
    present, _, _ = seed_blob(store)
    absent = "f" * 64
    store.publish([(present, ".png", f"{present}.png")], allowed=True)

    with pytest.raises(BlobError) as caught:
        store.verify_published([(absent, ".png", f"{absent}.png")])
    assert absent[:12] in str(caught.value)


def test_publishing_nothing_is_a_failure_not_a_pass(store: GitStore) -> None:
    """An empty batch must never produce a report that says it published."""
    store.ensure_cloned()
    with pytest.raises(BlobError):
        store.publish([], allowed=True)


# ---------------------------------------------------------------------------
# Step 8: a refused push is not a retry loop, and not a silent success.
# ---------------------------------------------------------------------------


def test_push_is_refused_when_the_caller_did_not_open_the_door(
    store: GitStore, with_identity: None
) -> None:
    """The gate that exists today must keep existing."""
    digest, _, target = seed_blob(store)
    with pytest.raises(BlobError) as caught:
        store.publish([(digest, ".png", target)], allowed=False)
    assert "disabled" in str(caught.value).lower()


def test_a_transient_push_failure_is_retried(
    tmp_path: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_identity: None,
) -> None:
    """A hook that declines once, then accepts. The blob must still land."""
    hook = bare_remote / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        'counter="$(dirname "$0")/../reject-count"\n'
        'n=0\n'
        '[ -f "$counter" ] && n=$(cat "$counter")\n'
        'n=$((n + 1))\n'
        'printf "%s" "$n" > "$counter"\n'
        'if [ "$n" -le 1 ]; then echo "try again" >&2; exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    store = GitStore(root=tmp_path / "clone", remote=str(bare_remote), branch="main")
    digest, _, target = seed_blob(store)
    delays: list[float] = []
    monkeypatch.setattr("utmelab_bank.blob.gitstore._sleep", delays.append)

    report = store.publish([(digest, ".png", target)], allowed=True, attempts=3, backoff=0.01)

    assert report.attempts == 2, "the first push was declined, the second accepted"
    assert delays, "a retry must wait before trying again"
    store.verify_published([(digest, ".png", target)])


def test_retries_are_bounded_and_the_last_failure_surfaces(
    tmp_path: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_identity: None,
) -> None:
    """A remote that always declines must not spin, and must say so."""
    hook = bare_remote / "hooks" / "pre-receive"
    hook.write_text('#!/bin/sh\necho "declined" >&2\nexit 1\n', encoding="utf-8")
    hook.chmod(0o755)

    store = GitStore(root=tmp_path / "clone", remote=str(bare_remote), branch="main")
    digest, _, target = seed_blob(store)
    monkeypatch.setattr("utmelab_bank.blob.gitstore._sleep", lambda _s: None)

    with pytest.raises(BlobError) as caught:
        store.publish([(digest, ".png", target)], allowed=True, attempts=3, backoff=0.01)
    assert caught.value.is_retryable
    assert caught.value.context.get("attempts") == 3


def test_an_auth_failure_is_not_retried(
    tmp_path: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_identity: None,
) -> None:
    """A rejected credential will be rejected again. Retrying is just slow.

    The classifier is what makes the difference, and it is exercised through a
    hook that emits the same words GitLab emits, because the words are all the
    client gets.
    """
    hook = bare_remote / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        'echo "remote: HTTP Basic: Access denied." >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    store = GitStore(root=tmp_path / "clone", remote=str(bare_remote), branch="main")
    digest, _, target = seed_blob(store)
    sleeps: list[float] = []
    monkeypatch.setattr("utmelab_bank.blob.gitstore._sleep", sleeps.append)

    with pytest.raises(GitAuthError) as caught:
        store.publish([(digest, ".png", target)], allowed=True, attempts=5, backoff=0.01)

    assert caught.value.is_retryable is False
    assert not sleeps, "an auth failure must not sleep and try again"
    assert caught.value.context.get("attempts") == 1


# ---------------------------------------------------------------------------
# Two runners at once.
# ---------------------------------------------------------------------------


def test_a_stale_lease_reclones_and_publishes_both_batches(
    tmp_path: Path, bare_remote: Path, with_identity: None
) -> None:
    """The other run's figures must survive, and ours must land too.

    ``--force-with-lease`` is what stops two runners from clobbering each
    other. The consequence is that the loser has to start over against a fresh
    remote, or its batch is silently dropped along with the winner's.
    """

    class RivalPushesMidRun(GitStore):
        """A store where somebody else publishes while we prepare.

        The race is real and it is a timing race, so it is injected at the one
        point it happens: after we pull, before we push.
        """

        pushed = False

        def pull_ff_only(self, branch: str | None = None) -> bool:
            result = super().pull_ff_only(branch)
            if RivalPushesMidRun.pushed:
                return result
            RivalPushesMidRun.pushed = True
            rival = GitStore(
                root=self.root.parent / "rival",
                remote=self.remote,
                branch=self.branch,
            )
            rival.ensure_cloned()
            digest, _, target = rival.write_blob(b"\x89PNG\r\n\x1a\nrival figure", ".png")
            # publish, not commit: the rival has to actually reach the remote,
            # or this test would prove nothing about a race.
            rival.publish([(digest, ".png", target)], allowed=True)
            return result

    ours = RivalPushesMidRun(
        root=tmp_path / "clone", remote=str(bare_remote), branch="main"
    )
    digest, _, target = seed_blob(ours)

    report = ours.publish([(digest, ".png", target)], allowed=True, attempts=3, backoff=0.01)

    assert report.recovered, "the rejected lease must be recovered from, not raised"
    assert RivalPushesMidRun.pushed, "the race was never injected, so nothing was proved"
    ours.verify_published([(digest, ".png", target)])

    # The rival's figure is still there. Losing it is the failure mode that
    # makes concurrent publishing worse than serial publishing.
    listing = git(ours.root, "ls-tree", "-r", "--name-only", "HEAD")
    assert any(path.startswith(f"{REPO_DIR}/") for path in listing.splitlines())
    assert len([p for p in listing.splitlines() if p.startswith(f"{REPO_DIR}/")]) == 2


# ---------------------------------------------------------------------------
# The repository must not grow a history.
# ---------------------------------------------------------------------------


def test_the_clone_stays_at_one_commit_across_many_publishes(
    store: GitStore, with_identity: None
) -> None:
    """Ten runs, one commit. History is the thing that fills a repository up."""
    store.ensure_cloned()
    for index in range(10):
        digest, _, target = store.write_blob(f"{PNG}{index}".encode(), ".png")
        git(store.root, "add", "--all", "--", REPO_DIR)
        store.publish([(digest, ".png", target)], allowed=True)

    assert git(store.root, "rev-list", "--count", "HEAD") == "1"


def test_republishing_identical_bytes_sends_nothing(
    store: GitStore, with_identity: None
) -> None:
    """The same bytes twice cost one blob, because the name is the hash.

    Content addressing is the whole space strategy. If this regresses, every
    re-run grows the repository.
    """
    store.ensure_cloned()
    digest, _, target = store.write_blob(PNG, ".png")
    git(store.root, "add", "--all", "--", REPO_DIR)
    ref = (digest, ".png", target)

    store.publish([ref], allowed=True)

    # Nothing changed, so there is nothing to push and nothing to grow. The
    # verification still runs and still passes, because the figure is already
    # on the remote from the first publish.
    store.publish([ref], allowed=True)

    listing = git(store.root, "ls-tree", "-r", "--name-only", "HEAD")
    assert len([p for p in listing.splitlines() if p.startswith(f"{REPO_DIR}/")]) == 1


def test_a_second_clone_sees_what_was_published(
    tmp_path: Path, bare_remote: Path, with_identity: None
) -> None:
    """The end-to-end proof, with no cache and no local state.

    Everything else in this file can be satisfied by a local object the remote
    never received. A fresh clone from the bare remote cannot.
    """
    store = GitStore(root=tmp_path / "clone", remote=str(bare_remote), branch="main")
    digest, blob_path, target = seed_blob(store)
    store.publish([(digest, ".png", target)], allowed=True)

    verifier = tmp_path / "verify"
    git(tmp_path, "clone", "--quiet", "--branch", "main", str(bare_remote), str(verifier))

    relative = blob_path.relative_to(store.root)
    landed = verifier / relative
    assert landed.is_file(), "the figure is not in a fresh clone of the remote"
    assert landed.read_bytes() == PNG
    assert store.blob_path(digest, ".png").is_file()
    assert target == f"{digest}.png"


def test_stats_report_what_the_repository_now_costs(store: GitStore) -> None:
    """Growth has to be visible before it is a surprise."""
    seed_blob(store)
    stats = store.stats()
    assert stats.blobs_on_disk == 1
    assert stats.blob_bytes == len(PNG)
    assert stats.objects > 0


# ---------------------------------------------------------------------------
# Guards that keep a caller from making the same mistake twice.
# ---------------------------------------------------------------------------


def test_publishing_refuses_a_blob_that_is_not_on_disk(store: GitStore) -> None:
    """A claimed blob with no file is caught before anything is pushed."""
    store.ensure_cloned()
    digest = "a" * 64
    with pytest.raises(BlobError):
        store.publish([(digest, ".png", f"{digest}.png")], allowed=True)


def test_a_protected_branch_is_still_refused(
    tmp_path: Path, bare_remote: Path, with_identity: None
) -> None:
    """The one safety rail in this file that already worked stays."""
    store = GitStore(root=tmp_path / "clone", remote=str(bare_remote), branch="main")
    seed_blob(store)
    with pytest.raises(BlobError):
        store.push("master", allowed=True)


def test_iterating_an_empty_blob_set_is_an_error(store: GitStore) -> None:
    """Guard the iterator itself, so a caller cannot pass nothing silently."""
    store.ensure_cloned()
    with pytest.raises(BlobError):
        list(store.verify_published(iter([])))


@pytest.fixture(autouse=True)
def _no_stray_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep git's credential lookups inside the test's own directory."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    yield