#!/usr/bin/env python3
"""Scrape every College Physics 2e module that the book still needs.

    python3 scripts/scrape_physics_modules.py

The modules that are already scraped are left alone. The images land in
data/concepts/images, which is local staging, and the figures are referenced
by the chapters.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLECTIONS = ROOT / "data/coverage/college-physics-collections.json"
REPO = "osbooks-college-physics-bundle"


def main():
    collections = json.loads(COLLECTIONS.read_text())
    wanted = []
    for collection in collections:
        for module in collection["modules"]:
            if not (ROOT / f"data/concepts/phy_{module}.json").exists():
                wanted.append(module)
    print(f"{len(wanted)} modules to scrape")
    for index, module in enumerate(wanted, start=1):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/scrape_openstax_cnx.py"),
                REPO,
                module,
                f"phy_{module}",
                "physics",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        tail = (result.stdout or result.stderr).strip().splitlines()
        print(f"[{index}/{len(wanted)}] {module}: {tail[-1][:90] if tail else 'no output'}")
        if result.returncode != 0:
            print("    failed, will retry")


if __name__ == "__main__":
    main()
