#!/usr/bin/env python3
"""Scrape every NECO subject that myschool actually carries.

The full run is 9 subjects across 53 subject-years. Each scope is a separate
fetch, so a stopped job loses no rows: the next run reloads the same scope,
finds the rows already at DEDUPED, and skips their figures.

The production half of the index is reloaded first. Without it, an old
question already served by production would look new and be scraped again.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence

from utmelab_bank.config import load_settings
from utmelab_bank.runtime import open_pipeline_runtime
from utmelab_bank.tasks import TaskOptions, run_named, summary

logger = logging.getLogger(__name__)

# Catalog slug -> the years myschool carries for that subject. The years come
# from the source's own exam filter, not from a guess or a full 2000-2026 sweep.
SCOPES: dict[str, tuple[int, ...]] = {
    "biology": (2000, 2001, 2002, 2003, 2004, 2005, 2008, 2009),
    "commerce": (2000, 2001, 2002, 2003, 2004, 2005, 2007, 2009),
    "physics": (2000, 2001, 2002, 2003, 2004, 2005, 2009),
    "government": (2001, 2002, 2003, 2004, 2005, 2009),
    "economics": (2002, 2003, 2004, 2005, 2007, 2009),
    "english": (2001, 2002, 2003, 2004, 2005, 2008, 2009),
    "mathematics": (2001, 2002, 2003, 2004, 2005, 2008),
    "chemistry": (2001, 2003, 2008, 2009),
    "computer-studies": (2014,),
}


def _selected(
    subjects: Sequence[str] | None,
    years: Sequence[int] | None,
) -> dict[str, tuple[int, ...]]:
    """Narrow the run to the scopes named on the command line."""
    wanted_subjects = set(subjects) if subjects else set(SCOPES)
    wanted_years = set(years) if years else None
    selected: dict[str, tuple[int, ...]] = {}
    for subject, available in SCOPES.items():
        if subject not in wanted_subjects:
            continue
        chosen = tuple(year for year in available if wanted_years is None or year in wanted_years)
        if chosen:
            selected[subject] = chosen
    return selected


async def _run(args: argparse.Namespace) -> int:
    selected = _selected(args.subject, args.year)
    if not selected:
        print("error: no NECO scope matched the filters", file=sys.stderr)
        return 2

    settings = load_settings()
    failures = 0
    totals = {"seen": 0, "done": 0, "skipped": 0, "errors": 0}

    async with open_pipeline_runtime(
        settings,
        source_name="myschool",
        media=not args.dry_run,
    ) as runtime:
        if not args.dry_run and not args.skip_index:
            indexed = await run_named("index", runtime, TaskOptions(limit=args.limit))
            print(f"index: {summary(indexed)}")
            if not indexed.ok:
                for error in indexed.errors:
                    print(f"  ERROR: {error}", file=sys.stderr)
                print("error: the production index could not be reloaded", file=sys.stderr)
                return 1

        for subject, years in selected.items():
            for year in years:
                options = TaskOptions(
                    exam="NECO",
                    subject=subject,
                    year=year,
                    limit=args.limit,
                    dry_run=args.dry_run,
                )
                try:
                    result = await run_named("fetch", runtime, options)
                except Exception as exc:  # one bad scope must not stop the rest
                    logger.exception("NECO/%s/%s failed", subject, year)
                    print(
                        f"NECO/{subject}/{year}: ERROR {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    failures += 1
                    continue

                print(f"NECO/{subject}/{year}: {summary(result)}")
                totals["seen"] += result.seen
                totals["done"] += result.done
                totals["skipped"] += result.skipped
                totals["errors"] += len(result.errors)
                if not result.ok:
                    failures += 1
                    for error in result.errors:
                        print(f"  ERROR: {error}", file=sys.stderr)

    print(
        "total: "
        f"{totals['seen']} seen, {totals['done']} deduped, "
        f"{totals['skipped']} filtered, {totals['errors']} errors, "
        f"{failures} failed scope(s)"
    )
    return 0 if failures == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subject",
        action="append",
        choices=sorted(SCOPES),
        help="run only this subject (repeatable)",
    )
    parser.add_argument(
        "--year",
        action="append",
        type=int,
        help="run only this year (repeatable)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="at most this many source rows per scope (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="probe the scopes without writing anything",
    )
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="assume the production index is already current",
    )
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
