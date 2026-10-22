"""The media clone, and the only code that shells out to git.

The clone is the store. ``media_fetch`` writes into it, ``media_transform``
writes derivatives into it, ``media_upload`` is ``git add`` plus one commit plus
one push, and ``media_gc`` is a scoped ``git clean``. There is no second copy of
the bytes anywhere, because with git as the destination a separate cache
directory would only duplicate every file.

Three rules earn their keep here, and all three are about not believing git.

**A command that fails raises.** ``_git`` returns the completed process, and
every caller decides what a non-zero exit means. The one caller that used to
swallow it is the one that cost us two published figures.

**An empty stdout is not a message.** Git writes some errors to stderr, so a
check that reads stdout alone sees the empty string and concludes nothing went
wrong. Anything that branches on git's words reads both streams.

**Nothing is published until the remote says so.** :meth:`GitStore.publish`
asks the remote for its ref, compares it to ours, and reads every blob back out
of the published tree. A push that exits zero has only proven that git accepted
the request.

Push is disabled by default, behind :meth:`GitStore.push_enabled`, and the
flag is separate from the remote so that "nobody opened the door" and "there is
no door" stay distinguishable in the error.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from utmelab_bank.blob.paths import (
    REPO_DIR,
    blob_path_for,
    ensure_inside,
    path_for,
    sha256_of,
    name_for,
)
from utmelab_bank.errors import BlobError, GitAuthError, GitPublishError

__all__ = ["BlobRef", "CloneStats", "GitStore", "PushReport"]

#: Never rewritten by us. The blobs are addressed by content, so a rewrite would
#: change every url in the bank for no benefit.
_PROTECTED: Final[tuple[str, ...]] = ("master",)

#: How long a single git command may take. Generous, because a first push of a
#: few hundred figures over a slow link is not a hung process.
_GIT_TIMEOUT: Final[int] = 600

#: Words git and GitLab use when the credential is the problem. Matched on the
#: combined output because the client only ever relays the server's words.
#: Anything not matched here is treated as worth retrying, which is the safe
#: default: an unnecessary retry costs seconds, a missed retry costs the run.
_AUTH_MARKERS: Final[tuple[str, ...]] = (
    "authentication failed",
    "http basic: access denied",
    "could not read username",
    "could not read password",
    "invalid username or password",
    "permission denied",
    "403 forbidden",
    "401 unauthorized",
    "access denied",
    "repository not found",
    "support for password authentication was removed",
)

#: Words that mean somebody else got there first, so the answer is to re-read
#: the remote and try again rather than to fail.
_STALE_MARKERS: Final[tuple[str, ...]] = (
    "stale info",
    "fetch first",
    "non-fast-forward",
    "cannot lock ref",
    "reference already exists",
)

#: Words that mean the server will not let this branch be rewritten. GitLab
#: protects the default branch by default and refuses a force push even to a
#: maintainer. The answer is not to fail, it is to append an ordinary commit.
_PROTECTED_MARKERS: Final[tuple[str, ...]] = (
    "protected branch",
    "not allowed to force push",
)

#: One message for every publish. The project is kept at a single commit where
#: the branch allows it, so there is normally only one commit message to read.
_COMMIT_MESSAGE: Final[str] = "media: publish fetched figures"

#: One blob, as the caller knows it: the digest, the extension it was stored
#: with, and the path it is published under. All three come from the row, and
#: the extension is per row because the bytes decide it.
BlobRef = tuple[str, str, str]


@dataclass(frozen=True)
class PushReport:
    """What one publish actually did, measured rather than asserted.

    ``files`` and ``sha`` are read back from the remote afterwards, so a caller
    that logs this is logging a fact. The attempt count is here because "it
    worked" and "it worked on the fourth try" are different things to say in a
    run summary.
    """

    files: int
    bytes_added: int
    pack_bytes: int
    seconds: float
    committed: bool
    branch: str
    sha: str = ""
    attempts: int = 1
    recovered: bool = False
    squashed: bool = True


@dataclass(frozen=True)
class CloneStats:
    """What the clone weighs. Answering "is this still small" cheaply."""

    objects: int
    size_bytes: int
    blobs_on_disk: int
    blob_bytes: int
    uncommitted: int


def _sleep(seconds: float) -> None:
    """The one place this module waits.

    A named function rather than a bare ``time.sleep`` so a test can observe
    the backoff without patching ``time`` itself, which would be global and
    would also capture every unrelated sleep in the process.
    """
    time.sleep(seconds)


def _restore_blobs(snapshot: Path, target: Path) -> int:
    """Copy our staged figures back over the other runner's tree.

    A plain filesystem copy rather than a git command, and the reason is worth
    recording: the first version of this shelled out to ``git cp``, which is
    not a git command, so it exited non-zero, and because the caller ignored
    that exit status the run continued and published a tree missing our own
    figure while reporting success. That is the same shape of bug as the one
    this whole module exists to prevent, so the copy raises on failure and the
    caller cannot miss it.

    A file that already exists is left alone. Blobs are addressed by their own
    hash, so two copies of the same figure are byte-identical and either is
    correct.
    """
    if not target.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    restored = 0
    for path in sorted(snapshot.rglob("*")):
        if not path.is_file():
            continue
        destination = target / path.relative_to(snapshot)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        restored += 1
    return restored


class GitStore:
    """A clone of the media project, addressed by content."""

    def __init__(self, root: Path, remote: str = "", branch: str = "main") -> None:
        # Absolute from the start. Every git command runs with this as its
        # working directory, so a relative root makes a relative clone
        # destination resolve against the destination itself, and the clone
        # lands one directory too deep.
        self.root = root.expanduser().resolve()
        self.remote = remote
        self.branch = branch

    # -- clone lifecycle --------------------------------------------------

    @property
    def exists(self) -> bool:
        return (self.root / ".git").is_dir()

    def ensure_cloned(self, remote: str | None = None) -> None:
        """Clone once. A no-op when the clone is already there.

        Idempotent so a workflow does not have to know whether it is the first
        run or the hundredth.

        The clone directory normally lives inside another checkout, under
        ``utmelab-bank/var/``. That is fine for a real clone and fatal for a
        half-made one, because with no ``.git`` of its own, every git command
        run here walks up and operates on the outer repository instead. So the
        path is created first and the clone is verified afterwards, and the
        failure says which directory was wrong.
        """
        target = remote or self.remote
        if self.exists:
            return
        if not target:
            raise BlobError(
                "no media remote configured",
                hint="set UTMELAB_BANK_MEDIA_REMOTE, or point --repo at a clone",
            )
        # git runs with the clone as its working directory, so the directory has
        # to exist first. Cloning into an empty directory is allowed.
        self.root.mkdir(parents=True, exist_ok=True)
        done = self._run(
            ["clone", "--depth", "1", "--branch", self.branch, target, str(self.root)]
        )
        if done.returncode != 0:
            raise BlobError(
                "could not clone the media remote",
                status=done.returncode,
                stderr=combined(done)[:400],
                hint="check the remote URL and the credential git will use for it",
            )
        if not self.exists:
            raise BlobError(
                "the media clone was not created",
                root=str(self.root),
                hint=(
                    "this directory must be empty and writable, "
                    "and not inside another git work tree"
                ),
            )

    def ensure_ready(self, *, with_identity: bool = True) -> None:
        """Everything that must hold before a commit is attempted.

        Checked up front rather than discovered at commit time. The identity
        check in particular: ``git commit`` failing on a missing ``user.email``
        is a three-line error at the far end of a run, and the run before that
        one reported success while it happened.
        """
        self.ensure_cloned()
        if with_identity:
            self.ensure_identity()

    def ensure_identity(self) -> None:
        """Refuse to proceed without a committer identity.

        Read through ``git var`` rather than ``git config``, because that is how
        git itself resolves it: environment variables count, and a CI runner
        that exports ``GIT_AUTHOR_EMAIL`` is configured even though no config
        file mentions it.
        """
        roles = (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT"))
        for role, variable in roles:
            done = self._run(["var", variable])
            if done.returncode != 0:
                raise BlobError(
                    f"git has no {role} identity, so no commit can be made",
                    variable=variable,
                    hint=(
                        'run: git config user.name "utmelab-bot" && '
                        'git config user.email "bot@utmelab.com"'
                    ),
                    detail_from=combined(done)[:300],
                )

    def _run(
        self,
        args: list[str],
        *,
        timeout: int = _GIT_TIMEOUT,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run one git command in the clone and hand back everything it said.

        The completed process rather than stdout, because the two failure modes
        this file exists to prevent both hide in the gap: a caller cannot see
        stderr, and a caller cannot see the exit status unless it is handed the
        process. It never raises on a non-zero exit; deciding what a failure
        means is the caller's job, and :meth:`_git` does it for the read-only
        callers that only want text.
        """
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(cwd or self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BlobError("git is not on the path") from exc
        except subprocess.TimeoutExpired as exc:
            raise BlobError("git timed out", args=args[:2], seconds=timeout) from exc

    def _git(self, args: list[str], *, check: bool = True, timeout: int = _GIT_TIMEOUT) -> str:
        """Run one git command and return its stdout.

        Kept for the many read-only callers that genuinely only want the text.
        Anything that branches on success or failure uses :meth:`_run`.
        """
        done = self._run(args, timeout=timeout)
        if check and done.returncode != 0:
            raise BlobError(
                "git failed",
                args=args[:3],
                status=done.returncode,
                stderr=combined(done)[:400],
            )
        return done.stdout.strip()

    # -- reading ----------------------------------------------------------

    def blob_path(self, digest: str, extension: str) -> Path:
        return blob_path_for(self.root, digest, extension)

    def has_blob(self, digest: str, extension: str) -> bool:
        return self.blob_path(digest, extension).is_file()

    def read_blob(self, digest: str, extension: str) -> bytes:
        path = ensure_inside(self.root, self.blob_path(digest, extension))
        if not path.is_file():
            raise BlobError("blob is not in the clone", digest=digest)
        return path.read_bytes()

    # -- writing ----------------------------------------------------------

    def write_blob(self, data: bytes, extension: str) -> tuple[str, Path, str]:
        """Store bytes, addressed by their hash. Returns ``(digest, path, url)``."""
        digest = sha256_of(data)
        path = self.blob_path(digest, extension)
        if path.is_file():
            return digest, path, name_for(digest, extension)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".partial")
        tmp.write_bytes(data)
        tmp.replace(path)
        return digest, path, name_for(digest, extension)

    def stage_all(self) -> int:
        """``git add`` everything untracked or changed under ``images`` and ``manifest``.

        Only paths that exist are named, because git refuses a pathspec matching
        nothing. A first upload on a clone with no ``manifest`` yet would
        otherwise fail before it ever staged the blob.
        """
        paths = [name for name in (REPO_DIR, "manifest") if (self.root / name).exists()]
        if not paths:
            return 0
        self._git(["add", "--all", "--", *paths])
        staged = self._git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
        return len([line for line in staged.splitlines() if line.strip()])

    def commit(self, message: str, *, amend: bool = False) -> str | None:
        """One commit. Returns the commit id, or ``None`` when there was nothing to do.

        ``amend`` keeps the project at a single commit, which is the plan for
        size and clone speed. Safety does not come from history: it comes from
        always pulling first, and from the manifest in the database being the
        record of what should exist.

        A non-zero exit raises. The two ways this can return ``None`` are the
        two that mean the same thing, and both are read from git's own words:
        nothing staged, or a fresh clone with no commits at all. Everything
        else is a failure, including the one this method used to swallow, where
        git exited 128 with "Committer identity unknown" on stderr and the
        previous sha came back as though it were a fresh one.
        """
        args = ["commit", "--amend", "--no-edit"] if amend else ["commit", "-m", message]
        done = self._run(args)
        words = combined(done).lower()

        if done.returncode != 0:
            if "nothing to commit" in words or "nothing added to commit" in words:
                # The legitimate no-op. The index matches the tree, so there is
                # nothing to record and the caller should carry on.
                return None
            raise BlobError(
                "git commit failed",
                args=args[:3],
                status=done.returncode,
                stderr=combined(done)[:400],
            )

        if not self.has_commits():
            # An empty repository with nothing staged produces no commit and
            # exits zero. Same meaning as above: there was nothing to do.
            return None
        return self._git(["rev-parse", "--short", "HEAD"])

    def has_commits(self) -> bool:
        return self._git(["rev-parse", "--verify", "HEAD"], check=False) != ""

    def pull_ff_only(self, branch: str | None = None) -> bool:
        """Bring the remote's commits before amending, so nothing unseen is dropped."""
        if not self.remote:
            return False
        target = branch or self.branch
        before = self._git(["rev-parse", "HEAD"], check=False)
        self._git(["pull", "--ff-only", "origin", target], check=False)
        return self._git(["rev-parse", "HEAD"], check=False) != before

    def push_enabled(self, config_flag: bool = False) -> bool:
        """Whether a push may happen.

        Two conditions, both required: the caller asked, and the remote is set.
        The uploaded bytes are candidates for production, so this stays closed
        until somebody opens it deliberately.
        """
        return bool(config_flag and self.remote)

    # -- publishing -------------------------------------------------------

    def publish(
        self,
        blobs: Iterable[BlobRef],
        *,
        allowed: bool = False,
        attempts: int = 3,
        backoff: float = 2.0,
        branch: str | None = None,
    ) -> PushReport:
        """Stage, commit, push, and then prove it. In that order, every time.

        ``blobs`` is the batch this call is publishing, as
        ``(digest, extension, published_path)`` triples taken from the rows. It
        is a required positional argument rather than an option because a
        publish that verifies nothing is exactly the failure this method
        exists to prevent, and an argument that can be left off is an argument
        that will be.

        The verification is the point. A push that exits zero has only shown
        that git accepted the request, which is also what happens when the
        commit never wrote anything and the push had nothing to send. So after
        pushing, the remote is asked where its ref is, that is compared to our
        HEAD, and every blob is read back out of the tree the remote is
        actually serving. Only then is this reported as published.

        A lease rejection is recovered from rather than raised, because it means
        another runner published in between and the answer is to re-read the
        remote and stage our batch again on top of theirs. Losing their figures
        to win a race is the wrong trade for a content store.

        A protected branch is handled the same way, with a different fallback.
        GitLab protects the default branch out of the box and refuses a force
        push even to a maintainer, so the rewrite this method prefers is simply
        not available there. Rather than fail, it appends an ordinary commit:
        the history grows by one small commit per run, while the blobs stay
        content-addressed and are never stored twice. A branch that does allow
        rewriting keeps the single-commit shape.
        """
        if not self.push_enabled(allowed):
            raise BlobError(
                "push is disabled",
                hint="set UTMELAB_BANK_MEDIA_UPLOAD_ENABLED=1 and UTMELAB_BANK_MEDIA_REMOTE",
            )
        refs = list(blobs)
        if not refs:
            raise GitPublishError(
                "publish was called with nothing to prove",
                hint="pass the blobs this run published; an empty batch cannot be verified",
            )
        missing = [ref for ref in refs if not self.has_blob(ref[0], ref[1])]
        if missing:
            raise BlobError(
                "cannot publish a blob that is not in the clone",
                digests=[digest[:12] for digest, _, _ in missing],
            )

        target = branch or self.branch
        if target in _PROTECTED and not self._is_default_branch(target):
            raise BlobError("refusing to push a protected branch", branch=target)

        # Everything that must be true before a commit is attempted, checked
        # here rather than by the caller. A caller that forgets to clone gets a
        # git error about an outer repository's .gitignore instead, which is
        # what happens when the clone directory sits inside another checkout:
        # there is no clone, so git walks up and finds the wrong repository.
        self.ensure_ready(with_identity=True)

        # Read the remote before amending. Amending rewrites the commit the
        # remote is serving, so anything published since our clone was made has
        # to come in first or this run silently drops it. A push that lands
        # after this fetch is caught by the lease and handled in the loop.
        self.pull_ff_only(target)

        started = time.monotonic()
        recovered = False
        squashed = True
        last: BlobError | None = None

        for attempt in range(1, max(1, attempts) + 1):
            # Stage and commit inside the loop, not before it. A recovery from
            # a lease rejection rewrites the base, so the index has to be built
            # again against whatever the remote holds now. A branch that cannot
            # be rewritten gets an ordinary commit on top of the fetched head
            # instead of an amended one.
            self.stage_all()
            self.commit(_COMMIT_MESSAGE, amend=squashed and self.has_commits())
            try:
                sha = self._push_once(target, force=squashed)
            except BlobError as exc:
                last = exc
                if squashed and _mentions(str(exc), _PROTECTED_MARKERS):
                    # The server will not rewrite this branch. Drop the amended
                    # commit and rebuild the same batch as a normal commit on
                    # top of the remote head. This does not consume the retry
                    # budget by itself; it is a change of strategy, not a
                    # transient failure.
                    squashed = False
                    self._restage(target)
                    continue
                if not exc.is_retryable or attempt >= attempts:
                    # Record what was spent before it leaves, so the operator
                    # sees "3 attempts" rather than a bare refusal.
                    exc.context["attempts"] = attempt
                    raise
                if _mentions(str(exc), _STALE_MARKERS):
                    # Somebody else got there first. Re-read the remote and
                    # stage our batch on top of theirs instead of clobbering it.
                    recovered = True
                    self._restage(target)
                _sleep(backoff * attempt)
                continue

            # Verification comes before the report. A report that exists before
            # the proof is a report that can be read by something that skipped
            # the proof, which is how the original bug stayed invisible.
            self.verify_published(refs, branch=target)
            return PushReport(
                files=len(refs),
                bytes_added=sum(self.blob_size(digest) for digest, _, _ in refs),
                pack_bytes=0,
                seconds=time.monotonic() - started,
                committed=True,
                branch=target,
                sha=sha,
                attempts=attempt,
                recovered=recovered,
                squashed=squashed,
            )

        # Unreachable while the loop either returns or raises, but a reader
        # should not have to prove that to trust the raise above it.
        raise last or GitPublishError("publish did not run")

    def _push_once(self, target: str, *, force: bool = True) -> str:
        """One push attempt. Returns the sha the remote should now be serving.

        Reads the remote back rather than trusting the exit status, so a push
        git considered a no-op cannot be reported as a publication.

        ``force`` is off only when the branch refused a rewrite. A plain push of
        a commit built on the fetched head is what a protected branch accepts.
        """
        if force:
            args = ["push", "--force-with-lease", "origin", f"HEAD:{target}"]
        else:
            args = ["push", "origin", f"HEAD:{target}"]
        done = self._run(args)
        if done.returncode != 0:
            raise self._classify_push_failure(done)
        return self.remote_head(target)

    def _classify_push_failure(self, done: subprocess.CompletedProcess[str]) -> BlobError:
        """Turn a push failure into the error a retry policy can act on.

        The distinction is the only thing worth making here. A refused
        credential is the same on the next attempt, so it must not be retried;
        everything else, from a declined hook to a dropped connection to
        somebody else's lease, clears on its own.
        """
        words = combined(done)
        context = {"status": done.returncode, "stderr": words[:400]}
        if _mentions(words, _AUTH_MARKERS):
            return GitAuthError("gitlab refused the credential", **context)
        return BlobError("git push failed", **context)

    def _restage(self, branch: str | None = None) -> None:
        """Rebuild our batch on top of whatever the other runner published.

        The snapshot before the reset is the whole point. ``reset --hard`` takes
        the working tree to the other runner's commit, which means our own
        figures are deleted from disk. Without a copy taken first, recovering
        from the lease trades "the other runner's figures were lost" for "ours
        were lost", which is not a recovery at all.

        The copy is cheap because the blobs are the only thing in the clone and
        they are named by their own hash, so restoring one is a plain file copy
        with nothing to reconcile.
        """
        target = branch or self.branch
        snapshot = self.root.parent / f".{self.root.name}-staging"
        shutil.rmtree(snapshot, ignore_errors=True)
        if (self.root / REPO_DIR).is_dir():
            shutil.copytree(self.root / REPO_DIR, snapshot / REPO_DIR)

        try:
            self._git(["fetch", "--depth", "1", "origin", target], check=False)
            # Take their tree wholesale. It is the state the remote is serving,
            # so building on it is the only version that can be pushed without
            # discarding somebody's work.
            self._git(["reset", "--hard", "FETCH_HEAD"], check=False)
            if (snapshot / REPO_DIR).is_dir():
                _restore_blobs(snapshot / REPO_DIR, self.root / REPO_DIR)

        finally:
            shutil.rmtree(snapshot, ignore_errors=True)

        self.stage_all()

    def remote_head(self, branch: str | None = None) -> str:
        """The commit the remote is serving for ``branch``, from the remote itself.

        ``ls-remote`` rather than a cached ``origin/main``, because a tracking
        ref is a memory of a push, and the question here is what the server
        holds right now.
        """
        target = branch or self.branch
        done = self._run(["ls-remote", "origin", f"refs/heads/{target}"])
        if done.returncode != 0:
            raise self._classify_push_failure(done)
        for line in done.stdout.splitlines():
            sha, _, ref = line.partition("\t")
            if ref.strip() == f"refs/heads/{target}":
                return sha.strip()
        return ""

    def verify_published(self, blobs: Iterable[BlobRef], *, branch: str | None = None) -> None:
        """Prove the remote is serving every blob, or raise.

        Three checks, because each catches a different lie. The remote ref has
        to be ours, so we know our commit is the one being served. Each blob has
        to exist in that commit's tree, so the figure is reachable by the path
        we published rather than merely present somewhere in the clone. And an
        empty set is an error, because a batch that verified nothing has proved
        nothing and would otherwise report success.
        """
        target = branch or self.branch
        refs = list(blobs)
        if not refs:
            raise GitPublishError(
                "nothing to verify",
                hint="a publish with no blobs cannot be confirmed",
            )

        remote = self.remote_head(target)
        if not remote:
            raise GitPublishError(
                "the remote has no such branch, so nothing was published",
                branch=target,
            )
        local = self._git(["rev-parse", "HEAD"], check=False)
        if local and remote != local:
            raise GitPublishError(
                "the remote is serving a different commit than the one we pushed",
                branch=target,
                remote=remote[:12],
                local=local[:12],
                hint="another runner may have published; run again",
            )

        absent = [
            published
            for digest, extension, published in refs
            if self._run(["cat-file", "-e", f"{remote}:{path_for(digest, extension)}"]).returncode
            != 0
        ]
        if absent:
            raise GitPublishError(
                "the remote does not hold every figure it was told to",
                missing=absent[:5],
                missing_count=len(absent),
                branch=target,
            )

    def blob_size(self, digest: str) -> int:
        """How many bytes a blob weighs on disk, or 0 when it is not there."""
        matches = sorted((self.root / REPO_DIR).glob(f"{digest}.*"))
        return matches[0].stat().st_size if matches else 0

    def push(self, branch: str | None = None, *, allowed: bool = False) -> PushReport:
        """Push the branch without staging, committing or verifying.

        Kept for the rare caller that wants the raw operation. The publish path
        should use :meth:`publish`, which is the one that proves anything.
        """
        if not self.push_enabled(allowed):
            raise BlobError(
                "push is disabled",
                hint="set UTMELAB_BANK_MEDIA_UPLOAD_ENABLED=1 and UTMELAB_BANK_MEDIA_REMOTE",
            )
        target = branch or self.branch
        if target in _PROTECTED and not self._is_default_branch(target):
            raise BlobError("refusing to push a protected branch", branch=target)
        sha = self._push_once(target)
        return PushReport(
            files=0,
            bytes_added=0,
            pack_bytes=0,
            seconds=0.0,
            committed=True,
            branch=target,
            sha=sha,
        )

    def _is_default_branch(self, branch: str) -> bool:
        return branch == self.branch

    # -- housekeeping -----------------------------------------------------

    def uncommitted(self) -> list[str]:
        out = self._git(["status", "--porcelain", "--", REPO_DIR, "manifest"], check=False)
        return [line for line in out.splitlines() if line.strip()]

    def stats(self) -> CloneStats:
        """What the clone weighs. Cheap enough for a nightly check."""
        count = self._git(["rev-list", "--objects", "--all"], check=False)
        objects = len([line for line in count.splitlines() if line.strip()])
        size_text = self._git(["count-objects", "-vH"], check=False)
        size_bytes = 0
        for line in size_text.splitlines():
            if line.startswith("size-pack:"):
                digits = "".join(ch for ch in line.split(":", 1)[1] if ch.isdigit() or ch == ".")
                if digits:
                    size_bytes = int(float(digits) * 1024 * 1024)
        blobs = list((self.root / REPO_DIR).rglob("*")) if (self.root / REPO_DIR).is_dir() else []
        files = [p for p in blobs if p.is_file()]
        return CloneStats(
            objects=objects,
            size_bytes=size_bytes,
            blobs_on_disk=len(files),
            blob_bytes=sum(p.stat().st_size for p in files),
            uncommitted=len(self.uncommitted()),
        )

    def clean_unreferenced(self, keep_hashes: set[str], *, dry_run: bool = True) -> list[Path]:
        """Remove blobs whose hash is not in ``keep_hashes``.

        A scoped ``rm``, not ``git clean``, because content addressing means the
        keep set is knowable without consulting the index.
        """
        removed: list[Path] = []
        media = self.root / REPO_DIR
        if not media.is_dir():
            return removed
        for path in media.rglob("*"):
            if not path.is_file() or path.name.endswith(".partial"):
                continue
            if path.stem in keep_hashes:
                continue
            removed.append(path)
            if not dry_run:
                path.unlink(missing_ok=True)
        return removed

    def destroy(self) -> None:
        """Delete the clone. Only for a clean re-clone."""
        if self.root.exists():
            shutil.rmtree(self.root)


PushMode = Literal["disabled", "amend", "branch"]


def combined(done: subprocess.CompletedProcess[str]) -> str:
    """Everything a finished git command said, on either stream.

    Git is inconsistent about which stream carries an error: "Committer
    identity unknown" arrives on stderr, while "nothing to commit" arrives on
    stdout. A check that reads one stream sees the empty string for half of all
    failures and concludes that nothing went wrong, which is precisely how a
    failed commit came to look like a successful one.
    """
    parts = [done.stdout.strip(), done.stderr.strip()]
    return "\n".join(part for part in parts if part)


def _mentions(words: str, markers: Sequence[str]) -> bool:
    """Whether git's output carries any of these words, case-insensitively."""
    lowered = words.lower()
    return any(marker in lowered for marker in markers)
