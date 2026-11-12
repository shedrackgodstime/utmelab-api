#!/usr/bin/env python3
"""The book media: what an image must be, and where it lives.

The bank's figures live in the media project under `images/`, addressed by
the sha256 of their bytes. The book has its own directory, `books/<book_id>/`,
so a chapter's figures never mix with the bank's.

The rules a figure must pass before it is shipped are here, so the validator,
the publisher and the factory agree on what "validated" means.

The manifest, `data/book-images.json`, is the record of what was published:
the local figure that was sent, where it went, and what the bytes were. The
factory reads it to point a figure at the published path, so a chapter can be
built without the image files on disk, and the validator reads it to check a
figure without fetching it.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The book's own directory inside the media project.
BOOKS_DIR = "books"

#: The largest figure we will ship. Anything larger is a scanned page, not a
#: figure, and the chapter should carry a cropped one.
MAX_BYTES = 1_500_000

#: The smallest figure worth shipping. Below this it is a rule or a dot.
MIN_DIMENSION = 32

#: Where the local figures live before they are published.
LOCAL_ROOTS = ("data/concepts", "data/book-images")

#: The record of what has been published.
MANIFEST = ROOT / "data/book-images.json"

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
)


class ImageProblem(Exception):
    """Why an image is not fit to ship."""


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_extension(data: bytes) -> str | None:
    """The extension the bytes declare. Servers lie, the bytes do not."""
    for magic, extension in _MAGIC:
        if data.startswith(magic):
            return extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def dimensions(data: bytes) -> tuple[int, int] | None:
    """The pixel size of a PNG or JPEG, read from its header."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return int(width), int(height)
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = struct.unpack(">H", data[index + 2 : index + 4])[0]
            index += 2 + length
    return None


def validate_image(data: bytes) -> dict:
    """Check the bytes and describe the image, or raise with the reason.

    A figure ships only when it is a real image, small enough, and big
    enough to read.
    """
    if not data:
        raise ImageProblem("the file is empty")
    extension = sniff_extension(data)
    if extension is None:
        raise ImageProblem("the bytes are not an image")
    if len(data) > MAX_BYTES:
        raise ImageProblem(f"the file is {len(data)} bytes, over the {MAX_BYTES} ceiling")
    size = dimensions(data)
    if size is None:
        raise ImageProblem("the image header carries no size")
    width, height = size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise ImageProblem(f"the image is {width}x{height}, under the {MIN_DIMENSION} pixel floor")
    return {
        "sha256": sha256_of(data),
        "extension": extension,
        "bytes": len(data),
        "width": width,
        "height": height,
    }


def local_path(asset_url: str) -> Path | None:
    """The file on disk for a figure that has not been published yet."""
    if asset_url.startswith(("http://", "https://", "data:", "//")):
        return None
    if asset_url.startswith(f"{BOOKS_DIR}/"):
        return None
    for root in LOCAL_ROOTS:
        candidate = ROOT / root / asset_url
        if candidate.exists():
            return candidate
    return None


def published_path(book_id: str, digest: str, extension: str) -> str:
    """Where a published figure lives inside the media project."""
    return f"{BOOKS_DIR}/{book_id}/{digest}{extension}"


def is_published(asset_url: str) -> bool:
    return asset_url.startswith(f"{BOOKS_DIR}/")


def empty_manifest() -> dict:
    return {"figures": {}, "rejected": {}}


def load_manifest() -> dict:
    """The record of what was published, and what was left out."""
    if not MANIFEST.exists():
        return empty_manifest()
    manifest = json.loads(MANIFEST.read_text())
    manifest.setdefault("figures", {})
    manifest.setdefault("rejected", {})
    return manifest


def save_manifest(manifest: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def published_for(manifest: dict, asset_url: str) -> str | None:
    """The published path for a local figure, if it was published."""
    record = manifest.get("figures", {}).get(asset_url)
    return record.get("published_path") if record else None


def was_rejected(manifest: dict, asset_url: str) -> str | None:
    """Why a figure was left out, if it was."""
    record = manifest.get("rejected", {}).get(asset_url)
    return record.get("reason") if record else None
