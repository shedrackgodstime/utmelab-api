"""Where a blob lives, addressed by its content.

The filename is the sha256 of the bytes. Three things fall out of that and all
three were the reason this design was chosen over a separate cache directory:

- Fetching is idempotent, because a hash already on disk means there is nothing
  to download.
- A transform is cached by its input plus its operation, so resizing the same
  figure twice computes once.
- Garbage collection needs no reference counting, because a blob is disposable
  the moment its row is uploaded and ready.

The layout is flat: ``images/<sha>.<ext>``, so the path is the name and nothing
else. A sharded layout (``images/ab/<sha>.<ext>``) keeps any one directory
smaller, which matters on a filesystem that lists slowly; the trade was made
for the simpler path a person can read off a url.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Final

from utmelab_bank.errors import BlobError

__all__ = [
    "REPO_DIR",
    "blob_path_for",
    "extension_for",
    "is_blob_name",
    "name_for",
    "path_for",
    "sha256_of",
    "sniff_extension",
]

#: The folder inside the media git project that holds the figures. The repo
#: layout lives here and nowhere else: what the bank stores is the bare file
#: name, and how a repo path or a web path is built from that name is this
#: module's job, not a column's.
REPO_DIR: Final[str] = "images"

_HASH_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{64}\.[a-z0-9]{1,5}$")

#: Leading bytes of the image formats we expect. The bytes are the truth here:
#: myschool serves real PNGs with ``content-type: text/plain``, which previously
#: filed every figure as ``.txt``.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_extension(data: bytes | None) -> str | None:
    """The extension the bytes themselves declare, or ``None`` when unknown."""
    if not data:
        return None
    for magic, extension in _MAGIC:
        if data.startswith(magic):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def extension_for(url: str, content_type: str | None = None, data: bytes | None = None) -> str:
    """The file extension to store under.

    The bytes win when we have them, because servers lie: a url ending in
    ``.jpg`` regularly serves a png, and myschool serves png as ``text/plain``.
    The content type and the url suffix are fallbacks for callers that only
    have the response headers.
    """
    sniffed = sniff_extension(data)
    if sniffed:
        return sniffed
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return ".jpg" if guessed == ".jpe" else guessed
    suffix = Path(url.split("?", maxsplit=1)[0]).suffix.lower()
    if suffix and len(suffix) <= 5 and suffix[1:].isalnum():
        return suffix
    return ".bin"


def _validate(extension: str) -> None:
    """Refuse an extension that is not plainly an extension.

    This path ends up inside a git index and a url, so a traversal or a space
    here is a file written outside the clone and a url that does not round
    trip. Checked once, in one place, because two callers that each spell the
    rule is how they drift apart.
    """
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", extension):
        raise BlobError("not a plain extension", extension=extension)


def blob_path_for(root: Path, digest: str, extension: str) -> Path:
    """The path a blob occupies, relative to the clone."""
    return root / path_for(digest, extension)


def is_blob_name(name: str) -> bool:
    return bool(_HASH_RE.match(name))


def path_for(digest: str, extension: str) -> str:
    """The blob's path inside the clone, as git addresses it.

    Always ``images/<sha>.<ext>`` and never a leading slash, because this is
    what ``git cat-file -e <commit>:<path>`` is asked about when a publish is
    verified. Writing that string by hand at the call site is how a leading
    slash or a missing prefix sneaks in and makes every verification fail for a
    reason that has nothing to do with the push.
    """
    _validate(extension)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BlobError("not a sha256 digest", digest=digest)
    return f"{REPO_DIR}/{digest}{extension}"


def name_for(digest: str, extension: str) -> str:
    """The file name a published figure is recorded under. Just the name.

    The bank stores this and nothing more: no ``images/``, no ``/media/`` and
    no host. Where the file sits in the git project and how the site serves it
    are decided by whoever reads it, so changing either is not a database
    migration. The name is content-addressed, which is what makes the row's
    identity survive any such move.
    """
    _validate(extension)
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise BlobError("not a sha256 digest", digest=digest)
    return f"{digest}{extension}"


def ensure_inside(root: Path, candidate: Path) -> Path:
    """Refuse a path outside the clone."""
    resolved = candidate.resolve()
    anchor = root.resolve()
    if resolved != anchor and anchor not in resolved.parents:
        raise BlobError("path escapes the clone", path=str(resolved), root=str(anchor))
    return resolved
