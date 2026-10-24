"""The bank's own schema.

Two tables. The staging table holds a row in flight. The passages table
holds the stimuli those rows refer to, because a passage is shared: 28 live
questions point at 8 passages, and a passage that lived inside a question
could not be shared and had nowhere to put its kind.

The catalog is not copied here: it is read from production, because
production is the authority for topic placement.
"""

from __future__ import annotations

from typing import Any

#: The one table the bank owns for content in flight.
STAGING = "staging_items"

#: The table the bank owns for the stimuli content refers to.
PASSAGES = "passages"

#: The table the bank owns for what it already knows about.
#:
#: The index holds the two fingerprints of every question the bank knows
#: about, whether it came from production or from the bank. Keeping it here
#: is what makes a duplicate check a lookup. Without it, every check would
#: scan the whole bank, and the scan grows with the bank.
CONTENT_INDEX = "content_index"

#: The table the bank owns for the reports it has already acted on.
#:
#: A report is acted on once. Recording that it was seen is what stops the
#: same complaint opening the same work every time the reports are read.
REPORT_LOG = "report_log"

#: The bank's tables, one statement each. The engine refuses a string with
#: more than one statement in it, so they are kept apart.
SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS staging_items (
        id              TEXT PRIMARY KEY,
        state           TEXT NOT NULL,
        exam            TEXT NOT NULL,
        subject         TEXT NOT NULL,
        year            INTEGER NOT NULL,
        country         TEXT,
        source          TEXT NOT NULL,
        source_item_id  TEXT NOT NULL,
        source_url      TEXT NOT NULL,
        payload_hash    TEXT NOT NULL,
        content_hash    TEXT NOT NULL,
        bundle_hash     TEXT NOT NULL,
        content         TEXT NOT NULL,
        passage         TEXT,
        catalog         TEXT,
        media           TEXT NOT NULL DEFAULT '[]',
        evidence        TEXT NOT NULL DEFAULT '{}',
        attempts        INTEGER NOT NULL DEFAULT 0,
        error           TEXT,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        section         TEXT,
        source_version  TEXT NOT NULL DEFAULT '1',
        media_refs      TEXT NOT NULL DEFAULT '[]',
        media_blobs     TEXT NOT NULL DEFAULT '{}'
    )
    """,
)

MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("passage", "ALTER TABLE staging_items ADD COLUMN passage TEXT"),
    ("section", "ALTER TABLE staging_items ADD COLUMN section TEXT"),
    ("country", "ALTER TABLE staging_items ADD COLUMN country TEXT"),
    (
        "source_version",
        "ALTER TABLE staging_items ADD COLUMN source_version TEXT NOT NULL DEFAULT '1'",
    ),
    (
        "media_refs",
        "ALTER TABLE staging_items ADD COLUMN media_refs TEXT NOT NULL DEFAULT '[]'",
    ),
    (
        "media_blobs",
        "ALTER TABLE staging_items ADD COLUMN media_blobs TEXT NOT NULL DEFAULT '{}'",
    ),
)

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_staging_state ON staging_items(state)",
    "CREATE INDEX IF NOT EXISTS idx_staging_scope ON staging_items(exam, subject, year)",
    "CREATE INDEX IF NOT EXISTS idx_staging_source ON staging_items(source, source_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_staging_content_hash ON staging_items(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_passages_scope ON passages(exam, subject)",
    "CREATE INDEX IF NOT EXISTS idx_content_index_near ON content_index(near_duplicate)",
    "CREATE INDEX IF NOT EXISTS idx_report_log_target ON report_log(target_type, target_id)",
)


def statements() -> tuple[str, ...]:
    """Every statement that brings a database to the current shape."""
    return (*SCHEMA, *INDEXES)


async def ensure_schema(client: Any) -> None:
    """Create the bank's tables and indexes if they are missing, then bring
    an older staging table up to the current shape."""
    for statement in statements():
        await client.execute(statement)
    await _migrate(client)


async def _migrate(client: Any) -> None:
    result = await client.execute("PRAGMA table_info(staging_items)")
    present = {str(row[1]) for row in result.rows}
    for column, statement in MIGRATIONS:
        if column not in present:
            await client.execute(statement)
    await client.execute(
        "CREATE INDEX IF NOT EXISTS idx_staging_scope_country "
        "ON staging_items(exam, country, subject, year)"
    )


__all__ = [
    "CONTENT_INDEX",
    "REPORT_LOG",
    "INDEXES",
    "MIGRATIONS",
    "PASSAGES",
    "SCHEMA",
    "STAGING",
    "ensure_schema",
    "statements",
]
