"""Small facts about image bytes that a store records."""

from __future__ import annotations

import io

from PIL import Image

__all__ = ["dimensions"]


def dimensions(data: bytes) -> tuple[int | None, int | None]:
    """The image size, or ``(None, None)`` when the bytes cannot be read.

    A store records this, but a store must not become the validator: the bytes
    that reach it have already been checked. A failure here is therefore not
    a reason to refuse a blob, only a reason to leave the columns empty.
    """
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except Exception:
        return None, None
    return width, height
