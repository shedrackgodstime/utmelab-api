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

__all__ = [
    "blob_path_for",
    "extension_for",
    "is_blob_name",
    "sha256_of",
    "sniff_extension",
    "url_for",
]

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
