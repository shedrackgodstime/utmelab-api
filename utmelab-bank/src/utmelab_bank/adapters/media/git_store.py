"""The media clone, and the only code here that shells out to git.

Ported from ``utmelab-bank-failed/src/utmelab_bank/blob/gitstore.py``, the copy
that has actually published figures to GitLab. Three rules earn their keep,
and all three are about not believing git.

**A command that fails raises.** ``_run`` hands back the process and every
caller decides what a non-zero exit means. The one caller that used to swallow
it is the one that cost two published figures.

**An empty stdout is not a message.** Git writes some errors to stderr, so
anything that branches on git's words reads both streams.

**Nothing is published until the remote says so.** ``publish`` asks the remote
for its ref, compares it to ours, and reads every blob back out of the
published tree. A push that exits zero has only proven that git accepted the
request, which is also what happens when the commit wrote nothing.

The store implements the ``MediaStore`` port. ``put`` writes a content
addressed blob and, when the push is open, publishes and proves it before it
returns. The url it hands back is the one the row will carry: the served url
built from the configured base, or the bare name when there is no base yet.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from utmelab_bank.domain.models import MediaAsset
from utmelab_bank.domain.ports import MediaStore

from .errors import MediaAuthError, MediaError, MediaPublishError
from .paths import (
    REPO_DIR,
    blob_path_for,
    ensure_inside,
    extension_for,
    is_digest,
    name_for,
    path_for,
    sha256_of,
)

__all__ = ["GitMediaStore", "PushReport", "BlobRef"]

#: Never rewritten by us. The blobs are addressed by content, so a rewrite
#: would change every url in the bank for no benefit.
_PROTECTED: Final[tuple[str, ...]] = ("master",)

#: How long a single git command may take. Generous, because a first push of a
#: few hundred figures over a slow link is not a hung process.
_GIT_TIMEOUT: Final[int] = 600

#: One message for every publish. The project is kept at a single commit where
#: the branch allows it.
_COMMIT_MESSAGE: Final[str] = "media: publish fetched figures"

#: Words git and GitLab use when the credential is the problem.
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

#: Words that mean somebody else got there first.
_STALE_MARKERS: Final[tuple[str, ...]] = (
    "stale info",
    "fetch first",
    "non-fast-forward",
    "cannot lock ref",
    "reference already exists",
)

#: Words that mean the server will not let this branch be rewritten.
_PROTECTED_MARKERS: Final[tuple[str, ...]] = (
    "protected branch",
    "not allowed to force push",
)

#: One blob, as the caller knows it: the digest, the extension it was stored
#: with, and the name it is published under. All three come from the bytes.
BlobRef = tuple[str, str, str]


@dataclass(frozen=True)
class PushReport:
    """What one publish actually did, measured rather than asserted."""

    files: int
    bytes_added: int
    seconds: float
    committed: bool
    branch: str
    sha: str = ""
    attempts: int = 1
    recovered: bool = False
    squashed: bool = True


def _sleep(seconds: float) -> None:
    """The one place this module waits, so a test can patch it if it must."""
    time.sleep(seconds)


def _restore_blobs(snapshot: Path, target: Path) -> int:
    """Copy our staged figures back over the other runner's tree.

    A plain filesystem copy rather than a git command: an earlier version
    shelled out to ``git cp`` (not a git command), ignored the exit status,
    and published a tree missing our own figure while reporting success. A
    file that already exists is left alone, because blobs are content
    addressed and two copies of one figure are byte-identical.
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


def _dimensions(data: bytes) -> tuple[int | None, int | None]:
    """The pixel size of an image, or ``(None, None)`` when it is not one."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
        return width, height
    except Exception:
        return None, None


class GitMediaStore(MediaStore):
    """A clone of the media project, addressed by content.

    Implements the ``MediaStore`` port. The git machinery is the proven one
    from the failed bank; what is new here is the port shape (``put`` /
    ``read`` / ``exists``) and the served url built from ``base_url``.
    """

    def __init__(
        self,
        root: Path,
        remote: str = "",
        branch: str = "main",
        *,
        base_url: str = "",
        upload_enabled: bool = False,
        attempts: int = 3,
    ) -> None:
        # Absolute from the start. Every git command runs with this as its
        # working directory, so a relative root resolves against itself and the
        # clone lands one directory too deep.
        self.root = Path(root).expanduser().resolve()
        self.remote = remote
        self.branch = branch
        self.base_url = base_url.rstrip("/")
        self.upload_enabled = upload_enabled
        self.attempts = attempts

    # -- clone lifecycle --------------------------------------------------

    @property
    def is_cloned(self) -> bool:
        return (self.root / ".git").is_dir()

    def ensure_cloned(self, remote: str | None = None) -> None:
        """Clone once. A no-op when the clone is already there.

        Without a remote this makes a local scratch repo, so a run can be
        wired and observed before the remote exists.
        """
        target = remote or self.remote
        if self.is_cloned:
            return
        # git runs with the clone as its working directory, so the directory
        # has to exist first. Cloning into an empty directory is allowed.
        self.root.mkdir(parents=True, exist_ok=True)
        if not target:
            done = self._run(["init", "-b", self.branch])
            if done.returncode != 0:
                raise MediaError(
                    "could not init a local media repo",
                    status=done.returncode,
                    stderr=combined(done)[:400],
                )
            # We made this repo, so we give it an identity. A real clone keeps
            # no identity of its own, which is what ``ensure_identity`` checks.
            self._git(["config", "user.name", "utmelab-bank"])
            self._git(["config", "user.email", "bank@utmelab.local"])
            return
        done = self._run(["clone", "--depth", "1", "--branch", self.branch, target, str(self.root)])
        if done.returncode != 0:
            raise MediaError(
                "could not clone the media remote",
                status=done.returncode,
                stderr=combined(done)[:400],
                hint="check the remote URL and the credential git will use for it",
            )
        if not self.is_cloned:
            raise MediaError(
                "the media clone was not created",
                root=str(self.root),
                hint="this directory must be empty and writable, and not inside another repo",
            )

    def ensure_ready(self, *, with_identity: bool = True) -> None:
        """Everything that must hold before a commit is attempted."""
        self.ensure_cloned()
        if with_identity:
            self.ensure_identity()

    def ensure_identity(self) -> None:
        """Refuse to proceed without a committer identity.

        Read through ``git var`` rather than ``git config``, because that is
        how git itself resolves it: environment variables count, and a runner
        that exports ``GIT_AUTHOR_EMAIL`` is configured even though no config
        file mentions it.
        """
        roles = (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT"))
        for role, variable in roles:
            done = self._run(["var", variable])
            if done.returncode != 0:
                raise MediaError(
                    f"git has no {role} identity, so no commit can be made",
                    variable=variable,
                    hint=(
                        'run: git config user.name "utmelab-bot" && '
                        'git config user.email "bot@utmelab.com"'
                    ),
                    detail=combined(done)[:300],
                )

    # -- running git ------------------------------------------------------

    def _run(
        self,
        args: list[str],
        *,
        timeout: int = _GIT_TIMEOUT,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run one git command in the clone and hand back everything it said.

        The completed process rather than stdout, because the two failure
        modes this file exists to prevent both hide in the gap: a caller
        cannot see stderr, and a caller cannot see the exit status.
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
            raise MediaError("git is not on the path") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaError("git timed out", args=args[:2], seconds=timeout) from exc

    def _git(self, args: list[str], *, check: bool = True, timeout: int = _GIT_TIMEOUT) -> str:
        """Run one git command and return its stdout.

        Kept for the read-only callers that only want text. Anything that
        branches on success or failure uses ``_run``.
        """
        done = self._run(args, timeout=timeout)
        if check and done.returncode != 0:
            raise MediaError(
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
            raise MediaError("blob is not in the clone", digest=digest)
        return path.read_bytes()

    def blob_path_any(self, digest: str) -> Path | None:
        """Find a blob by digest alone, since the extension is per row."""
        if not is_digest(digest):
            return None
        matches = sorted((self.root / REPO_DIR).glob(f"{digest}.*"))
        return matches[0] if matches else None

    # -- writing ----------------------------------------------------------

    def write_blob(self, data: bytes, extension: str) -> tuple[str, Path, str]:
        """Store bytes, addressed by their hash. Returns ``(digest, path, name)``."""
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
        """``git add`` everything untracked or changed under ``images``.

        Only paths that exist are named, because git refuses a pathspec that
        matches nothing.
        """
        if not (self.root / REPO_DIR).exists():
            return 0
        self._git(["add", "--all", "--", REPO_DIR])
        staged = self._git(["diff", "--cached", "--name-only", "--diff-filter=ACM"])
        return len([line for line in staged.splitlines() if line.strip()])

    def commit(self, message: str, *, amend: bool = False) -> str | None:
        """One commit. Returns the commit id, or ``None`` when there was nothing to do.

        ``amend`` keeps the project at a single commit where the branch allows
        it. A non-zero exit raises, except the two ways that legitimately mean
        nothing to do; everything else, including the missing-identity exit
        128, is a failure.
        """
        args = ["commit", "--amend", "--no-edit"] if amend else ["commit", "-m", message]
        done = self._run(args)
        words = combined(done).lower()

        if done.returncode != 0:
            if "nothing to commit" in words or "nothing added to commit" in words:
                return None
            raise MediaError(
                "git commit failed",
                args=args[:3],
                status=done.returncode,
                stderr=combined(done)[:400],
            )

        if not self.has_commits():
            return None
        return self._git(["rev-parse", "--short", "HEAD"])

    def has_commits(self) -> bool:
        return self._git(["rev-parse", "--verify", "HEAD"], check=False) != ""

    def pull_ff_only(self, branch: str | None = None) -> bool:
        """Bring the remote's commits in before amending, so nothing is dropped."""
        if not self.remote:
            return False
        target = branch or self.branch
        before = self._git(["rev-parse", "HEAD"], check=False)
        self._git(["pull", "--ff-only", "origin", target], check=False)
        return self._git(["rev-parse", "HEAD"], check=False) != before

    # -- publishing -------------------------------------------------------

    def push_enabled(self, config_flag: bool = False) -> bool:
        """Whether a push may happen. The caller must ask, and a remote must exist."""
        return bool(config_flag and self.remote)

    def publish(
        self,
        blobs: Iterable[BlobRef],
        *,
        allowed: bool = False,
        branch: str | None = None,
    ) -> PushReport:
        """Stage, commit, push, and then prove it. In that order, every time.

        The verification is the point. A push that exits zero has only shown
        that git accepted the request, which is also what happens when the
        commit never wrote anything and the push had nothing to send. So after
        pushing, the remote is asked where its ref is, that is compared to our
        HEAD, and every blob is read back out of the tree the remote is
        actually serving. Only then is this reported as published.
        """
        if not self.push_enabled(allowed):
            raise MediaError(
                "push is disabled",
                hint="set upload_enabled and a media remote",
            )
        refs = list(blobs)
        if not refs:
            raise MediaPublishError(
                "publish was called with nothing to prove",
                hint="pass the blobs this run published; an empty batch cannot be verified",
            )
        missing = [ref for ref in refs if not self.has_blob(ref[0], ref[1])]
        if missing:
            raise MediaError(
                "cannot publish a blob that is not in the clone",
                digests=[digest[:12] for digest, _, _ in missing],
            )

        target = branch or self.branch
        if target in _PROTECTED and not self._is_default_branch(target):
            raise MediaError("refusing to push a protected branch", branch=target)

        # Everything that must be true before a commit is attempted, checked
        # here rather than left to the caller to forget.
        self.ensure_ready(with_identity=True)
        # Read the remote before amending, so anything published since our
        # clone was made comes in first.
        self.pull_ff_only(target)

        started = time.monotonic()
        recovered = False
        squashed = True
        last: MediaError | None = None

        for attempt in range(1, max(1, self.attempts) + 1):
            # Stage and commit inside the loop: a recovery rewrites the base,
            # so the index has to be rebuilt against whatever the remote holds.
            self.stage_all()
            self.commit(_COMMIT_MESSAGE, amend=squashed and self.has_commits())
            try:
                sha = self._push_once(target, force=squashed)
            except MediaError as exc:
                last = exc
                if squashed and _mentions(str(exc), _PROTECTED_MARKERS):
                    # The server will not rewrite this branch. Rebuild the same
                    # batch as a normal commit on top of the remote head. This
                    # is a change of strategy, not a transient failure.
                    squashed = False
                    self._restage(target)
                    continue
                if not exc.is_retryable or attempt >= self.attempts:
                    exc.context["attempts"] = attempt
                    raise
                if _mentions(str(exc), _STALE_MARKERS):
                    # Somebody else got there first. Re-read the remote and
                    # stage our batch on top of theirs instead of clobbering.
                    recovered = True
                    self._restage(target)
                _sleep(2.0 * attempt)
                continue

            # Verification comes before the report.
            self.verify_published(refs, branch=target)
            return PushReport(
                files=len(refs),
                bytes_added=sum(self.blob_size(digest) for digest, _, _ in refs),
                seconds=time.monotonic() - started,
                committed=True,
                branch=target,
                sha=sha,
                attempts=attempt,
                recovered=recovered,
                squashed=squashed,
            )

        raise last or MediaPublishError("publish did not run")

    def _push_once(self, target: str, *, force: bool = True) -> str:
        """One push attempt. Returns the sha the remote should now be serving.

        Reads the remote back rather than trusting the exit status, so a push
        git considered a no-op cannot be reported as a publication.
        """
        if force:
            args = ["push", "--force-with-lease", "origin", f"HEAD:{target}"]
        else:
            args = ["push", "origin", f"HEAD:{target}"]
        done = self._run(args)
        if done.returncode != 0:
            raise self._classify_push_failure(done)
        return self.remote_head(target)

    def _classify_push_failure(self, done: subprocess.CompletedProcess[str]) -> MediaError:
        """Turn a push failure into the error a retry policy can act on."""
        words = combined(done)
        context: dict[str, Any] = {"status": done.returncode, "stderr": words[:400]}
        if _mentions(words, _AUTH_MARKERS):
            return MediaAuthError("gitlab refused the credential", **context)
        return MediaError("git push failed", **context)

    def _restage(self, branch: str | None = None) -> None:
        """Rebuild our batch on top of whatever the other runner published.

        The snapshot taken before the reset is the whole point: ``reset --hard``
        takes the working tree to the other runner's commit, which deletes our
        figures from disk. Without a copy taken first, recovering would trade
        one runner's figures for the other's.
        """
        target = branch or self.branch
        snapshot = self.root.parent / f".{self.root.name}-staging"
        shutil.rmtree(snapshot, ignore_errors=True)
        if (self.root / REPO_DIR).is_dir():
            shutil.copytree(self.root / REPO_DIR, snapshot / REPO_DIR)

        try:
            self._git(["fetch", "--depth", "1", "origin", target], check=False)
            self._git(["reset", "--hard", "FETCH_HEAD"], check=False)
            if (snapshot / REPO_DIR).is_dir():
                _restore_blobs(snapshot / REPO_DIR, self.root / REPO_DIR)
        finally:
            shutil.rmtree(snapshot, ignore_errors=True)

        self.stage_all()

    def remote_head(self, branch: str | None = None) -> str:
        """The commit the remote is serving for ``branch``, from the remote."""
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
        to be ours, so our commit is the one being served. Each blob has to
        exist in that commit's tree, so the figure is reachable by the path we
        published. And an empty set is refused, because a batch that verified
        nothing has proved nothing.
        """
        target = branch or self.branch
        refs = list(blobs)
        if not refs:
            raise MediaPublishError("nothing to verify")

        remote = self.remote_head(target)
        if not remote:
            raise MediaPublishError(
                "the remote has no such branch, so nothing was published",
                branch=target,
            )
        local = self._git(["rev-parse", "HEAD"], check=False)
        if local and remote != local:
            raise MediaPublishError(
                "the remote is serving a different commit than the one we pushed",
                branch=target,
                remote=remote[:12],
                local=local[:12],
                hint="another runner may have published; run again",
            )

        absent = [
            name
            for digest, extension, name in refs
            if self._run(["cat-file", "-e", f"{remote}:{path_for(digest, extension)}"]).returncode
            != 0
        ]
        if absent:
            raise MediaPublishError(
                "the remote does not hold every figure it was told to",
                missing=absent[:5],
                missing_count=len(absent),
                branch=target,
            )

    def blob_size(self, digest: str) -> int:
        """How many bytes a blob weighs on disk, or 0 when it is not there."""
        matches = sorted((self.root / REPO_DIR).glob(f"{digest}.*"))
        return matches[0].stat().st_size if matches else 0

    def _is_default_branch(self, branch: str) -> bool:
        return branch == self.branch

    def url_for(self, digest: str, extension: str) -> str:
        """The url the row will carry for this blob.

        The served url when a base is configured, and the bare name otherwise.
        The bare name is the bank's record; only an ``https`` url can go into
        an inline, so a store with no base cannot hand ownership over and the
        row keeps its source url.
        """
        name = name_for(digest, extension)
        if self.base_url:
            return f"{self.base_url}/{name}"
        return name

    # -- the MediaStore port ----------------------------------------------

    async def put(
        self,
        data: bytes,
        *,
        mime: str,
        source_url: str | None = None,
    ) -> MediaAsset:
        """Write a blob and, when the push is open, publish and prove it."""
        if not data:
            raise MediaError("refusing to store empty bytes")
        # The clone has to exist first: a remote clone lands in an empty
        # directory, and writing the blob before it would make that directory
        # non-empty and the clone would refuse.
        self.ensure_ready(with_identity=True)
        extension = extension_for(source_url or "", mime, data)
        digest, _path, name = self.write_blob(data, extension)
        ref: BlobRef = (digest, extension, name)

        if self.push_enabled(self.upload_enabled):
            self.publish([ref], allowed=True)
        else:
            # Local only: record the bytes with a commit, but claim nothing.
            self.stage_all()
            self.commit(_COMMIT_MESSAGE)

        width, height = _dimensions(data)
        return MediaAsset(
            asset_id=digest,
            mime=mime,
            byte_size=len(data),
            width=width,
            height=height,
            storage_url=self.url_for(digest, extension),
            source_url=source_url,
            fetched_at=datetime.now(UTC),
            required=True,
            readable=True,
        )

    async def read(self, asset_id: str) -> bytes:
        path = self.blob_path_any(asset_id)
        if path is None:
            raise MediaError("media asset not found", asset_id=asset_id)
        return path.read_bytes()

    async def exists(self, asset_id: str) -> bool:
        return self.blob_path_any(asset_id) is not None


def combined(done: subprocess.CompletedProcess[str]) -> str:
    """Everything a finished git command said, on either stream.
    Git is inconsistent about which stream carries an error: "Committer
    identity unknown" arrives on stderr, while "nothing to commit" arrives on
    stdout. A check that reads one stream sees the empty string for half of
    all failures and concludes nothing went wrong.
    """
    parts = [done.stdout.strip(), done.stderr.strip()]
    return "\n".join(part for part in parts if part)


def _mentions(words: str, markers: Sequence[str]) -> bool:
    """Whether git's output carries any of these words, case-insensitively."""
    lowered = words.lower()
    return any(marker in lowered for marker in markers)
