"""The bank's own schema.

One table holds a staging row. The catalog is not copied here: it is read from
production, because production is the authority for topic placement.
"""

from __future__ import annotations

from typing import Any

#: The one table the bank owns.
STAGING = "staging_items"

SCHEMA = """
CREATE TABLE IF NOT EXISTS staging_items (
    id              TEXT PRIMARY KEY,
    state           TEXT NOT NULL,
    exam            TEXT NOT NULL,
    subject         TEXT NOT NULL,
    year            INTEGER NOT NULL,
    source          TEXT NOT NULL,
    source_item_id  TEXT NOT NULL,
    source_url      TEXT NOT NULL,
    payload_hash    TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    bundle_hash     TEXT NOT NULL,
    content         TEXT NOT NULL,
    catalog         TEXT,
    media           TEXT NOT NULL DEFAULT '[]',
    evidence        TEXT NOT NULL DEFAULT '{}',
    attempts        INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_staging_state ON staging_items(state)",
    "CREATE INDEX IF NOT EXISTS idx_staging_scope ON staging_items(exam, subject, year)",
    "CREATE INDEX IF NOT EXISTS idx_staging_source ON staging_items(source, source_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_staging_content_hash ON staging_items(content_hash)",
)


def statements() -> tuple[str, ...]:
    """Every statement that brings a database to the current shape."""
    return (SCHEMA, *INDEXES)


async def ensure_schema(client: Any) -> None:
    """Create the bank's table and its indexes if they are missing."""
    for statement in statements():
        await client.execute(statement)


__all__ = ["INDEXES", "SCHEMA", "STAGING", "ensure_schema", "statements"]
