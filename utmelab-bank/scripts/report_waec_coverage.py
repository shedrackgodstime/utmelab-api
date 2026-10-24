"""Report WAEC catalog and question coverage from production."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from utmelab_bank.adapters.database import prod_client
from utmelab_bank.adapters.sources.myschool.subjects import load_map
from utmelab_bank.config import load_settings


async def report(year: int) -> dict[str, Any]:
    settings = load_settings(require=False)
    client = prod_client(settings)
    try:
        subjects = await client.execute(
            "SELECT slug, name FROM subjects WHERE exam = ? ORDER BY slug",
            ["WAEC"],
        )
        counts = await client.execute(
            "SELECT subject, COUNT(*) FROM questions WHERE exam = ? AND year = ? GROUP BY subject",
            ["WAEC", year],
        )
    finally:
        await client.close()

    source_map = load_map().exam("WAEC").by_slug
    question_counts = {str(row[0]): int(row[1]) for row in counts.rows}
    catalog = []
    for row in subjects.rows:
        slug = str(row[0])
        entry = source_map.get(slug)
        catalog.append(
            {
                "subject": slug,
                "name": str(row[1]),
                "source_slug": entry.source if entry else None,
                "questions": question_counts.get(slug, 0),
                "covered": question_counts.get(slug, 0) > 0,
            }
        )

    return {
        "exam": "WAEC",
        "year": year,
        "subjects": catalog,
        "unmapped_subjects": [row["subject"] for row in catalog if row["source_slug"] is None],
        "missing_questions": [row["subject"] for row in catalog if not row["covered"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(report(args.year)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
