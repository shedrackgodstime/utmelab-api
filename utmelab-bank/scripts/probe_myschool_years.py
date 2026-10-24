"""Probe mapped MySchool subjects for rows belonging to one exam year."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from typing import Any

from utmelab_bank.adapters.sources.myschool import MyschoolSource
from utmelab_bank.adapters.sources.myschool.parser import (
    api_last_page,
    listing_url,
    parse_api_listing,
)
from utmelab_bank.adapters.sources.myschool.subjects import subjects_for

PAGE_DELAY = 1.0
DEFAULT_MAX_PAGES = 50


async def probe(exam: str, year: int, max_pages: int) -> dict[str, Any]:
    source = MyschoolSource()
    results: list[dict[str, Any]] = []
    try:
        for entry in subjects_for(exam).subjects:
            seen_rows = 0
            years: Counter[int] = Counter()
            pages = 0
            last_page = 0
            errors: list[str] = []
            try:
                payload = await source._get_json(  # noqa: SLF001
                    listing_url(exam.lower(), entry.source, year, 1)
                )
                last_page = api_last_page(payload)
                pages_to_scan = min(last_page, max_pages)
                for page in range(1, pages_to_scan + 1):
                    if page > 1:
                        await asyncio.sleep(PAGE_DELAY)
                        payload = await source._get_json(  # noqa: SLF001
                            listing_url(exam.lower(), entry.source, year, page)
                        )
                    rows = parse_api_listing(payload)
                    if not rows:
                        break
                    for row in rows:
                        collection = row.get("collection")
                        if not isinstance(collection, dict):
                            continue
                        raw_year = collection.get("exam_year")
                        if isinstance(raw_year, int) and not isinstance(raw_year, bool):
                            years[raw_year] += 1
                    seen_rows += len(rows)
                    pages = page
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

            if years.get(year, 0):
                status = "available"
            elif errors:
                status = "unavailable_or_mismatched"
            else:
                status = "no_data"
            results.append(
                {
                    "subject": entry.slug,
                    "source_slug": entry.source,
                    "rows_seen": seen_rows,
                    "pages_scanned": pages,
                    "pages_available": last_page,
                    "truncated": last_page > max_pages,
                    "available_years": dict(sorted(years.items())),
                    "matching_year_count": years.get(year, 0),
                    "errors": sorted(set(errors))[:5],
                    "status": status,
                }
            )
    finally:
        await source.close()
    return {"exam": exam.upper(), "year": year, "subjects": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exam", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    args = parser.parse_args()
    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    print(json.dumps(asyncio.run(probe(args.exam, args.year, args.max_pages)), indent=2))


if __name__ == "__main__":
    main()
