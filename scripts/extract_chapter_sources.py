#!/usr/bin/env python3
"""Extract the source material the chapter factory reads, into a tracked place.

    python3 scripts/extract_chapter_sources.py

The factory reads two things that live outside the repository: the concept
documents in `data/concepts/`, and the scraped solutions in
`data/staging/`. Both are gitignored, so a clean checkout cannot rebuild a
chapter, and the content gate that checks a chapter against its spec fails
for the wrong reason: it cannot find the source at all.

This script copies the part of that source the factory needs into
`data/chapter-sources/`, one file per module, and nothing else. The blocks
are the source's own prose, figures, examples and exercises. The solutions
for the module travel with it, because an exercise without its solution is
not an exercise.

    data/concepts/*.json                  the concept documents (gitignored)
    data/staging/openstax_clean_solutions.json   the solutions (gitignored)
        │
        ▼  scripts/extract_chapter_sources.py
    data/chapter-sources/<module>.json     the source material, tracked
        │
        ▼  scripts/build_chapter.py
    data/chapters/<chapter_id>.json        the built artifact
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONCEPTS = ROOT / "data/concepts"
SOLUTIONS = ROOT / "data/staging/openstax_clean_solutions.json"
SPECS = ROOT / "data/chapter-specs"
OUT = ROOT / "data/chapter-sources"


def modules_the_specs_need() -> set[str]:
    """The source modules the specs name. Nothing else is extracted."""
    needed: set[str] = set()
    for path in sorted(SPECS.glob("*.json")):
        spec = json.loads(path.read_text())
        for section in spec.get("sections", []):
            module = section.get("module")
            if module:
                needed.add(module)
    return needed


def concept_by_module() -> dict[str, dict]:
    """The concept document for each source module."""
    found: dict[str, dict] = {}
    for path in sorted(CONCEPTS.glob("*.json")):
        if path.name.startswith("audit-"):
            continue
        try:
            document = json.loads(path.read_text())
        except Exception:
            continue
        source = document.get("source_attribution") or {}
        module = source.get("section") or ""
        if module and module not in found:
            found[module] = document
    return found


def main() -> int:
    needed = modules_the_specs_need()
    if not needed:
        print("no spec names a source module")
        return 1

    solutions: dict = {}
    if SOLUTIONS.exists():
        solutions = json.loads(SOLUTIONS.read_text())

    concepts = concept_by_module()
    missing = sorted(needed - set(concepts))
    if missing:
        print(f"no concept document for {len(missing)} modules:")
        for module in missing[:20]:
            print(f"    {module}")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()

    written = 0
    for module in sorted(needed):
        concept = concepts[module]
        source = concept.get("source_attribution") or {}
        blocks = (concept.get("deep_context") or {}).get("blocks", [])
        book = source.get("book") or ""
        prefix = f"{book}:{module}:"
        module_solutions = {
            key: value for key, value in solutions.items() if key.startswith(prefix)
        }
        document = {
            "module": module,
            "source_attribution": source,
            "blocks": blocks,
            "solutions": module_solutions,
        }
        (OUT / f"{module}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        )
        written += 1

    blocks = sum(
        len(json.loads((OUT / f"{module}.json").read_text())["blocks"])
        for module in sorted(needed)
    )
    print(
        f"wrote {written} module extracts to {OUT.relative_to(ROOT)}: "
        f"{blocks} blocks, {len(solutions)} solutions read"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
