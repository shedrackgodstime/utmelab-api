#!/usr/bin/env python3
"""Publish the book's figures to the media project, and only the valid ones.

    python3 scripts/publish_book_images.py --dry-run
    python3 scripts/publish_book_images.py

The figures live in the media project under their own directory,
`books/<book_id>/`, addressed by the sha256 of their bytes, the same
convention the bank uses for its own figures. A figure ships only when it
passes the checks in `scripts/book_media.py`: real image bytes, a size
ceiling, and a pixel floor. The rest are recorded as rejected, with the
reason, so the factory leaves them out and the validator can say why.

The figures are read from the source extracts, not from the built chapters,
because a built chapter already points at the published path. The book a
figure belongs to comes from the spec that names its module.

Uploads go through the Commits API with many files per commit, because a
file at a time would be a thousand commits for a book's figures. The batch
is sized by bytes, not by file count, so one oversized figure cannot make
the request too large.

The manifest of what was published is written to `data/book-images.json`.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_media  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BANK_ENV = ROOT / "utmelab-bank" / ".env"
SOURCES = ROOT / "data/chapter-sources"
SPECS = ROOT / "data/chapter-specs"
DEFAULT_PROJECT = "shedrackgodstime/utmelab-bank"
DEFAULT_BRANCH = "main"

#: The largest commit we will ask GitLab to take. The API accepts more, but a
#: request this size fails fast, and a failed request is cheaper than a
#: half-written commit.
BATCH_BYTES = 4_000_000

#: The most files in one commit. Each file is a separate action in the
#: request, and a request with thousands of actions is slow to build.
BATCH_FILES = 40


def read_env() -> dict:
    values = {}
    if BANK_ENV.exists():
        for line in BANK_ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def gitlab_settings() -> tuple[str, str, str, str]:
    env = read_env()
    host = os.environ.get("GITLAB_HOST") or env.get("GITLAB_HOST") or "gitlab.com"
    project = (
        os.environ.get("GITLAB_MEDIA_REPO") or env.get("GITLAB_MEDIA_REPO") or DEFAULT_PROJECT
    )
    token = os.environ.get("GITLAB_TOKEN") or env.get("GITLAB_TOKEN") or ""
    branch = (
        os.environ.get("UTMELAB_BANK_MEDIA_BRANCH")
        or env.get("UTMELAB_BANK_MEDIA_BRANCH")
        or DEFAULT_BRANCH
    )
    return host, project, token, branch


class GitLab:
    """The repository API, the way the bank's media store writes."""

    def __init__(self, host: str, project: str, token: str, branch: str):
        if not token:
            raise SystemExit(
                "no GitLab token: set GITLAB_TOKEN or put it in utmelab-bank/.env"
            )
        self.branch = branch
        self.token = token
        self.api = f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(project, safe='')}"

    def _request(self, method: str, path: str, **kwargs):
        import httpx

        return httpx.request(
            method,
            f"{self.api}{path}",
            headers={"PRIVATE-TOKEN": self.token},
            timeout=300,
            **kwargs,
        )

    def published_files(self) -> set[str]:
        """Every file already in the project, so nothing is written twice."""
        import httpx

        found: set[str] = set()
        page = 1
        while True:
            response = httpx.get(
                f"{self.api}/repository/tree",
                headers={"PRIVATE-TOKEN": self.token},
                params={
                    "ref": self.branch,
                    "recursive": "true",
                    "per_page": 100,
                    "page": page,
                },
                timeout=300,
            )
            if response.status_code != 200:
                raise SystemExit(
                    f"could not list the media project: {response.status_code} "
                    f"{response.text[:200]}"
                )
            entries = response.json()
            if not entries:
                break
            for entry in entries:
                if entry.get("type") == "blob":
                    found.add(entry["path"])
            if len(entries) < 100:
                break
            page += 1
        return found

    def commit(self, files: list[tuple[str, bytes]], message: str) -> bool:
        """Write a batch of files in one commit."""
        actions = [
            {
                "action": "create",
                "file_path": path,
                "content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
            }
            for path, data in files
        ]
        response = self._request(
            "POST",
            "/repository/commits",
            json={
                "branch": self.branch,
                "commit_message": message,
                "actions": actions,
            },
        )
        if response.status_code not in (200, 201):
            print(f"    commit failed: {response.status_code} {response.text[:300]}")
            return False
        return True


def module_books() -> dict[str, str]:
    """The book each source module belongs to, from the specs."""
    books: dict[str, str] = {}
    for path in sorted(SPECS.glob("*.json")):
        spec = json.loads(path.read_text())
        book_id = spec["book_id"]
        for section in spec.get("sections", []):
            module = section.get("module")
            if module:
                books[module] = book_id
    return books


def collect(book_filter: str | None):
    """Every figure the source extracts use, with the book it belongs to.

    The same figure is often used by several chapters and several sections,
    so the work is keyed by the published path. Two chapters that share a
    figure share the bytes and share the path.
    """
    books = module_books()
    wanted: dict[str, dict] = {}
    rejected: dict[str, str] = {}
    order: list[str] = []
    # The figure a source used, and the published path it became.
    assets: dict[str, str] = {}

    for path in sorted(SOURCES.glob("*.json")):
        document = json.loads(path.read_text())
        module = document["module"]
        book_id = books.get(module)
        if book_id is None:
            continue
        if book_filter and book_id != book_filter:
            continue
        for block in document.get("blocks", []):
            if block.get("type") != "figure":
                continue
            asset = block.get("asset_url") or ""
            if not asset or book_media.is_published(asset):
                continue
            local = book_media.local_path(asset)
            if local is None:
                rejected[asset] = "the file is not on disk"
                continue
            data = local.read_bytes()
            try:
                described = book_media.validate_image(data)
            except book_media.ImageProblem as error:
                rejected[asset] = str(error)
                continue
            target = book_media.published_path(
                book_id, described["sha256"], described["extension"]
            )
            if target not in wanted:
                wanted[target] = {
                    "data": data,
                    "book_id": book_id,
                    "source": str(local.relative_to(ROOT)),
                    **described,
                }
                order.append(target)
            assets[asset] = target

    return wanted, rejected, order, assets


def batches(files: list[tuple[str, bytes]]):
    """Split the files into batches, sized by bytes and by count."""
    current: list[tuple[str, bytes]] = []
    size = 0
    for path, data in files:
        if current and (size + len(data) > BATCH_BYTES or len(current) >= BATCH_FILES):
            yield current
            current = []
            size = 0
        current.append((path, data))
        size += len(data)
    if current:
        yield current


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would ship, and change nothing"
    )
    parser.add_argument("--book", help="only this book")
    args = parser.parse_args()

    host, project, token, branch = gitlab_settings()
    wanted, rejected, order, assets = collect(args.book)

    total_bytes = sum(len(item["data"]) for item in wanted.values())
    print(f"valid figures:   {len(wanted)}")
    print(f"their bytes:     {total_bytes / 1e6:.1f} MB")
    print(f"left out:        {len(rejected)}")
    for asset, reason in sorted(rejected.items()):
        print(f"    {asset}: {reason}")

    manifest = book_media.load_manifest()
    manifest.setdefault("figures", {})
    manifest.setdefault("rejected", {})

    for asset, reason in rejected.items():
        manifest["rejected"][asset] = {"reason": reason}

    for asset, target in assets.items():
        item = wanted[target]
        manifest["figures"][asset] = {
            "sha256": item["sha256"],
            "extension": item["extension"],
            "bytes": item["bytes"],
            "width": item["width"],
            "height": item["height"],
            "book_id": item["book_id"],
            "source": item["source"],
            "published_path": target,
        }

    if args.dry_run:
        print(f"commits it would take: {len(list(batches([(p, wanted[p]['data']) for p in order])))}")
        return 0

    gitlab = GitLab(host, project, token, branch)
    already_there = gitlab.published_files()
    pending = [
        (path, wanted[path]["data"]) for path in order if path not in already_there
    ]
    print(f"already in the project: {len(order) - len(pending)}")
    print(f"to upload:              {len(pending)}")

    uploaded = 0
    failed = 0
    for batch in batches(pending):
        book_of_batch = batch[0][0].split("/")[1]
        message = f"book: {book_of_batch} figures ({len(batch)} files)"
        if not gitlab.commit(batch, message):
            failed += len(batch)
            continue
        uploaded += len(batch)
        print(f"  committed {len(batch)} figures ({uploaded}/{len(pending)})")

    print(f"uploaded: {uploaded}")
    print(f"failed:   {failed}")

    if failed:
        print("the manifest was not written: the figures are not all there")
        return 1

    book_media.save_manifest(manifest)
    print(f"manifest written to data/book-images.json ({len(manifest['figures'])} figures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
