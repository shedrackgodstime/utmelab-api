#!/usr/bin/env python3
"""Bundle the books and the chapters into one file the importer can read.

    python3 scripts/bundle_chapters.py

The importer takes {"books": [...], "chapters": [...]}. This gathers the
book documents and the chapter documents into that shape, so the import is one
write rather than thirty four.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS = ROOT / "data/books"
CHAPTERS = ROOT / "data/chapters"
OUT = ROOT / "data/staging/chapters-bundle.json"


def main():
    books = []
    for path in sorted(BOOKS.glob("*.json")):
        document = json.loads(path.read_text())
        # The book document carries a chapter list for the reader. The importer
        # takes the chapters themselves, so the list is dropped here, and the
        # id is named the way the store names it.
        document.pop("chapters", None)
        document["id"] = document.pop("book_id")
        books.append(document)

    chapters = []
    for path in sorted(CHAPTERS.glob("*.json")):
        chapters.append(json.loads(path.read_text()))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"books": books, "chapters": chapters}, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {OUT}: {len(books)} books, {len(chapters)} chapters")


if __name__ == "__main__":
    main()
