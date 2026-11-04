#!/usr/bin/env python3
"""Clean orphaned bank index entries.

Removes content_index rows (origin='bank') that have no corresponding
staging_items row. Run after any manual staging cleanup or migration.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utmelab_bank.adapters.database import bank_client
from utmelab_bank.config import load_settings


async def main(dry_run: bool = True) -> None:
    settings = load_settings()
    client = bank_client(settings)

    try:
        # Count orphans
        result = await client.execute("""
            SELECT COUNT(*) FROM content_index ci
            LEFT JOIN staging_items si ON ci.question_id = si.id
            WHERE ci.origin = 'bank' AND si.id IS NULL
        """)
        orphan_count = int(result.rows[0][0])
        print(f"Orphaned bank index entries: {orphan_count}")

        if orphan_count == 0:
            print("Nothing to clean.")
            return

        if dry_run:
            print("DRY RUN: No changes made. Re-run with --apply to execute.")
            return

        # Delete orphans
        result = await client.execute("""
            DELETE FROM content_index
            WHERE origin = 'bank'
            AND question_id NOT IN (SELECT id FROM staging_items)
        """)
        print(f"Deleted {orphan_count} orphaned index entries.")

        # Verify
        result = await client.execute("""
            SELECT COUNT(*) FROM content_index ci
            LEFT JOIN staging_items si ON ci.question_id = si.id
            WHERE ci.origin = 'bank' AND si.id IS NULL
        """)
        remaining = int(result.rows[0][0])
        print(f"Remaining orphans: {remaining}")

        total = await client.execute("SELECT COUNT(*) FROM content_index WHERE origin = 'bank'")
        print(f"Total bank index entries: {int(total.rows[0][0])}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main("--apply" not in sys.argv))