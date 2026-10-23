"""Probe mapped MySchool subjects for rows belonging to one exam year."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

from utmelab_bank.adapters.sources.myschool import MyschoolSource
from utmelab_bank.adapters.sources.myschool.subjects import subjects_for
from utmelab_bank.domain.models import Scope

SAMPLE_LIMIT = 100
YEAR_MISMATCH = re.compile(r"from \w+ (\d+), not \w+ \d+")


async def probe(exam: str, year: int) -> dict[str, Any]:
    source = MyschoolSource()
    results: list[dict[str, Any]] = []
    try:
        for entry in subjects_for(exam).subjects:
            sample_count = 0
            matching_count = 0
            mismatched_years: set[int] = set()
            errors: list[str] = []
            scope = Scope(exam=exam, subject=entry.slug, year=year)
            try:
                async for item in source.fetch(scope):
                    sample_count += 1
                    error = item.payload.get("error")
                    if isinstance(error, dict):
                        message = str(error.get("message", error))
                        errors.append(message)
                        match = YEAR_MISMATCH.search(message)
                        if match:
                            mismatched_years.add(int(match.group(1)))
                    else:
                        matching_count += 1
                    if sample_count >= SAMPLE_LIMIT:
                        break
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
