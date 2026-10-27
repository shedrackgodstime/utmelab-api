"""The pinned source manifest."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Source:
    subject: str
    name: str
    page: str | None
    pdf: str
    sha256: str
    bytes: int
    pages: int


def load_manifest(path: Path) -> dict[str, Source]:
    data = json.loads(path.read_text())
    return {
        slug: Source(
            subject=slug,
            name=item["name"],
            page=item.get("page"),
            pdf=item["pdf"],
            sha256=item["sha256"],
            bytes=int(item["bytes"]),
            pages=int(item["pages"]),
        )
        for slug, item in data["subjects"].items()
    }


def cache_dir() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "utmelab" / "syllabus-pdfs"


def fetch(source: Source, destination: Path) -> Path:
    """Download once, then verify the pinned hash on every use."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        request = urllib.request.Request(
            source.pdf,
            headers={"User-Agent": "utmelab-catalog/0.1 (educational project)"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            destination.write_bytes(response.read())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    if digest != source.sha256:
        raise ValueError(
            f"{source.subject}: {destination} has hash {digest}, expected {source.sha256}"
        )
    return destination


__all__ = ["Source", "cache_dir", "fetch", "load_manifest"]
