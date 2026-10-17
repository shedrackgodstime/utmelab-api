"""Where a blob lives, addressed by its content.

The filename is the sha256 of the bytes. Three things fall out of that and all
three were the reason this design was chosen over a separate cache directory:

- Fetching is idempotent, because a hash already on disk means there is nothing
  to download.
- A transform is cached by its input plus its operation, so resizing the same
  figure twice computes once.
- Garbage collection needs no reference counting, because a blob is disposable
  the moment its row is uploaded and ready.

The layout is two levels deep because one directory with fifty thousand files is
slow to list on the filesystem we run on.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

from utmelab_bank.errors import BlobError

__all__ = ["blob_path_for", "url_for", "extension_for", "sha256_of", "is_blob_name"]

_HASH_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}\.[a-z0-9]{1,5}$")


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extension_for(url: str, content_type: str | None = None) -> str:
    """The file extension to store under.

    From the content type when the server gave one, because a url ending in
    ``.jpg`` regularly serves a png.
    """
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix and len(suffix) <= 5 and suffix[1:].isalnum():
        return suffix
    return ".bin"


def blob_path_for(root: Path, digest: str, extension: str) -> Path:
    """The path a blob occupies, relative to the clone.

    Raises when the extension is not a plain extension, because this path ends
    up inside a git index and a traversal here would be a file written outside
    the clone.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BlobError("not a sha256 digest", digest=digest)
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", extension):
        raise BlobError("not a plain extension", extension=extension)
    return root / "media" / digest[:2] / f"{digest}{extension}"


def is_blob_name(name: str) -> bool:
    return bool(_HASH_RE.match(name))


def url_for(digest: str, extension: str) -> str:
    """The path we publish, which is ours and not the provider's.

    Storing our own path rather than a gitlab url is what makes moving off the
    media project a configuration change instead of a rewrite of every question
    row that carries a figure.
    """
    return f"/media/{digest[:2]}/{digest}{extension}"


def ensure_inside(root: Path, candidate: Path) -> Path:
    """Refuse a path outside the clone."""
    resolved = candidate.resolve()
    anchor = root.resolve()
    if resolved != anchor and anchor not in resolved.parents:
        raise BlobError("path escapes the clone", path=str(resolved), root=str(anchor))
    return resolved
