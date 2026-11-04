#!/usr/bin/env python3
"""
Audit script to export all rejected items with their rejection reasons.
Run in CI or locally to generate a CSV/JSON report.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utmelab_bank.adapters.database import get_client
from utmelab_bank.domain.models import StagingItem


def audit_rejected(exam: str | None = None, subject: str | None = None, year: int | None = None) -> list[dict]:
    """Fetch all rejected items with their error details."""
    client = get_client("bank")

    where_parts = ["state = 'rejected'"]
    params = []

    if exam:
        where_parts.append("exam = ?")
        params.append(exam)
    if subject:
        where_parts.append("subject = ?")
        params.append(subject)
    if year:
        where_parts.append("year = ?")
        params.append(year)

    where_clause = " AND ".join(where_parts)

    query = f"""
        SELECT id, exam, subject, year, source, source_item_id,
               state, error, content, evidence, catalog, attempts, updated_at
        FROM staging_items
        WHERE {where_clause}
        ORDER BY subject, year, id
    """

    rows = client.query(query, params)

    results = []
    for row in rows:
        # Parse error for categorization
        error = row.get("error", "")
        category = categorize_error(error)

        results.append({
            "id": row["id"],
            "exam": row["exam"],
            "subject": row["subject"],
            "year": row["year"],
            "source": row["source"],
            "source_item_id": row["source_item_id"],
            "error_category": category,
            "error_detail": error,
            "attempts": row.get("attempts", 0),
            "updated_at": row.get("updated_at", ""),
        })

    return results


def categorize_error(error: str) -> str:
    """Categorize error by type."""
    if not error:
        return "unknown"

    error_lower = error.lower()

    if "review_fail" in error_lower:
        return "canonical_answer_wrong"
    elif "not ready" in error_lower and "explanatory" in error_lower:
        return "explanation_mismatch"
    elif "evidence does not appear" in error_lower or "evidence not in" in error_lower:
        return "evidence_hallucination"
    elif "unknownsubtopic" in error_lower:
        return "unknown_subtopic"
    elif "lowconfidencetag" in error_lower or "confidence" in error_lower and "below" in error_lower:
        return "low_confidence"
    elif "providerexhausted" in error_lower:
        return "provider_exhausted"
    elif "kilo" in error_lower and ("json" in error_lower or "output" in error_lower):
        return "kilo_json_failure"
    elif "opencodeerror" in error_lower:
        return "opencode_failure"
    elif "valueerror" in error_lower:
        return "value_error"
    else:
        return "other"


def main():
    parser = argparse.ArgumentParser(description="Audit rejected items")
    parser.add_argument("--exam", help="Filter by exam (e.g., JAMB)")
    parser.add_argument("--subject", help="Filter by subject slug")
    parser.add_argument("--year", type=int, help="Filter by year")
    parser.add_argument("--output", "-o", help="Output file (CSV or JSON)")
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--summary", action="store_true", help="Print summary by category")

    args = parser.parse_args()

    items = audit_rejected(args.exam, args.subject, args.year)

    if args.summary:
        # Print summary
        from collections import Counter
        categories = Counter(item["error_category"] for item in items)
        subjects = Counter(item["subject"] for item in items)

        print(f"\n=== Rejected Items Audit ===")
        print(f"Total: {len(items)}")
        print(f"\nBy Category:")
        for cat, count in categories.most_common():
            print(f"  {cat}: {count}")
        print(f"\nBy Subject:")
        for subj, count in subjects.most_common():
            print(f"  {subj}: {count}")

    if args.output:
        path = Path(args.output)
        if args.format == "json":
            path.write_text(json.dumps(items, indent=2))
        else:
            if items:
                fieldnames = items[0].keys()
                with path.open("w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(items)
            else:
                path.write_text("No rejected items found\n")
        print(f"\nWritten to {path}")

    # Print first few for quick inspection
    for item in items[:10]:
        print(f"\n{item['id']} [{item['error_category']}]")
        print(f"  {item['error_detail'][:200]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())