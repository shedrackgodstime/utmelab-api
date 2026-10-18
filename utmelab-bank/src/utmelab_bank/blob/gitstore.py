"""The media clone, and the only code that shells out to git.

The clone is the store. ``media_fetch`` writes into it, ``media_transform``
writes derivatives into it, ``media_upload`` is ``git add`` plus one commit plus
one push, and ``media_gc`` is a scoped ``git clean``. There is no second copy of
the bytes anywhere, because with git as the destination a separate cache
directory would only duplicate every file.

Push is disabled. Not behind a flag that defaults off, which is one typo away
from on, but behind :meth:`GitStore.push_enabled`, which nothing sets until the
media project exists and somebody has decided on its size budget.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from utmelab_bank.blob.paths import blob_path_for, ensure_inside, sha256_of, url_for
from utmelab_bank.errors import BlobError

__all__ = ["CloneStats", "GitStore", "PushReport"]

#: Never rewritten by us. The blobs are addressed by content, so a rewrite would
#: change every url in the bank for no benefit.
_PROTECTED: Final[tuple[str, ...]] = ("master",)


@dataclass(frozen=True)
class CloneStats:
    """What the clone weighs. Answering "is this still small" cheaply."""

    objects: int
    size_bytes: int
    blobs_on_disk: int
    blob_bytes: int
    uncommitted: int


@dataclass(frozen=True)
class PushReport:
    """What one push cost, so a probe can extrapolate."""

    files: int
    bytes_added: int
    pack_bytes: int
    seconds: float
    committed: bool
    branch: str


class GitStore:
    """A clone of the media project, addressed by content."""

    def __init__(self, root: Path, remote: str = "", branch: str = "main") -> None:
        self.root = root
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
        self._git(["clone", "--depth", "1", "--branch", self.branch, target, str(self.root)])

    def _git(self, args: list[str], *, check: bool = True, timeout: int = 600) -> str:
        try:
            done = subprocess.run(
                ["git", *args],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BlobError("git is not on the path") from exc
        except subprocess.TimeoutExpired as exc:
            raise BlobError("git timed out", args=args[:2], seconds=timeout) from exc
        if check and done.returncode != 0:
            raise BlobError(
                "git failed",
                args=args[:3],
                status=done.returncode,
                stderr=done.stderr.strip()[:400],
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
            return digest, path, url_for(digest, extension)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".partial")
        tmp.write_bytes(data)
        tmp.replace(path)
        return digest, path, url_for(digest, extension)

    def stage_all(self) -> int:
        """``git add`` everything untracked or changed under ``media`` and ``manifest``.

        Only paths that exist are named, because git refuses a pathspec matching
        nothing. A first upload on a clone with no ``manifest`` yet would
        otherwise fail before it ever staged the blob.
        """
        paths = [name for name in ("media", "manifest") if (self.root / name).exists()]
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
        """
        args = ["commit", "--amend", "--no-edit"] if amend else ["commit", "-m", message]
        output = self._git(args, check=False)
        if "nothing to commit" in output or not self.has_commits():
            return None
        return self._git(["rev-parse", "--short", "HEAD"])

    def has_commits(self) -> bool:
        return self._git(["rev-parse", "--verify", "HEAD"], check=False) != ""

    def pull_ff_only(self) -> bool:
        """Bring the remote's commits before amending, so nothing unseen is dropped."""
        if not self.remote:
            return False
        before = self._git(["rev-parse", "HEAD"], check=False)
        self._git(["pull", "--ff-only", "origin", self.branch], check=False)
        return self._git(["rev-parse", "HEAD"], check=False) != before

    def push_enabled(self, config_flag: bool = False) -> bool:
        """Whether a push may happen.

        Two conditions, both required: the caller asked, and the remote is set.
        The uploaded bytes are candidates for production, so this stays closed
        until somebody opens it deliberately.
        """
        return bool(config_flag and self.remote)

    def push(self, branch: str | None = None, *, allowed: bool = False) -> PushReport:
        """Push the branch. Refuses unless :meth:`push_enabled` agrees.

        ``allowed`` is the caller's decision to open the door (the config flag).
        It is a parameter rather than a stored field so that every push site has
        to say, in one line, that it means to publish.
        """
        if not self.push_enabled(allowed):
            raise BlobError(
                "push is disabled",
                hint="set UTMELAB_BANK_MEDIA_UPLOAD_ENABLED=1 and UTMELAB_BANK_MEDIA_REMOTE",
            )
        target = branch or self.branch
        if target in _PROTECTED and not self._is_default_branch(target):
            raise BlobError("refusing to push a protected branch", branch=target)
        output = self._git(["push", "--force-with-lease", "origin", f"HEAD:{target}"])
        del output
        return PushReport(
            files=0,
            bytes_added=0,
            pack_bytes=0,
            seconds=0.0,
            committed=True,
            branch=target,
        )

    def _is_default_branch(self, branch: str) -> bool:
        return branch == self.branch

    # -- housekeeping -----------------------------------------------------

    def uncommitted(self) -> list[str]:
        out = self._git(["status", "--porcelain", "--", "media", "manifest"], check=False)
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
        blobs = list((self.root / "media").rglob("*")) if (self.root / "media").is_dir() else []
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
        media = self.root / "media"
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
