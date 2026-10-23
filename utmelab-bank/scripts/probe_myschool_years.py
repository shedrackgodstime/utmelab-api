"""Probe mapped MySchool subjects for rows belonging to one exam year."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from utmelab_bank.adapters.sources.myschool import MyschoolSource
from utmelab_bank.adapters.sources.myschool.parser import (
    listing_url,
    parse_api_listing,
    parse_api_question,
)
from utmelab_bank.adapters.sources.myschool.subjects import subjects_for

SAMPLE_LIMIT = 5


async def probe(exam: str, year: int) -> dict[str, Any]:
    source = MyschoolSource()
    results: list[dict[str, Any]] = []
    try:
        for entry in subjects_for(exam).subjects:
            sample_count = 0
            matching_count = 0
            mismatched_years: set[int] = set()
            errors: list[str] = []
            try:
                payload = await source._get_json(  # noqa: SLF001
                    listing_url(exam.lower(), entry.source, year, 1)
                )
                rows = parse_api_listing(payload)[:SAMPLE_LIMIT]
                sample_count = len(rows)
                for row in rows:
                    try:
                        parsed = parse_api_question(
                            row,
                            exam=exam.lower(),
                            subject=entry.slug,
                            year=year,
                            source_slug=entry.source,
                        )
                    except Exception as exc:
                        errors.append(f"{type(exc).__name__}: {exc}")
                        continue
                    if parsed.exam == exam.lower() and parsed.year == year:
                        matching_count += 1
                    else:
                        mismatched_years.add(parsed.year)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

            if matching_count:
                status = "available"
            elif errors:
                status = "unavailable_or_mismatched"
            else:
                status = "no_data"
            results.append(
                {
                    "subject": entry.slug,
                    "source_slug": entry.source,
                    "sample_count": sample_count,
                    "matching_year_count": matching_count,
                    "mismatched_years": sorted(mismatched_years),
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
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.exam, args.year)), indent=2))


if __name__ == "__main__":
    main()
