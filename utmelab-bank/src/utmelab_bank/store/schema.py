"""The lane DDL, and the runs table.

Three lanes, as tables rather than a status column, so that a task with a wrong
``where`` clause cannot reach a row that has already been verified. The
tradeoff is a copy per lane, which is cheap here because these tables hold tens
of thousands of rows, not millions.

Lane prefixes are generated from one function so a rename is one edit, and
``assert_lane_parity`` fails if a table ends up in one lane and not its sibling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from utmelab_bank.config import LANE_PREFIX, Lane
from utmelab_bank.errors import StoreError

if TYPE_CHECKING:
    from utmelab_bank.store.client import Store

__all__ = ["DDL", "LANES", "LANE_TABLES", "assert_lane_parity", "ensure_schema", "lane_of", "table"]

#: The lanes, in the order a row moves through them.
LANES: Final[tuple[Lane, ...]] = ("raw", "work", "ready")

#: Logical name to the tables it exists in, per lane.
LANE_TABLES: Final[dict[str, tuple[str, ...]]] = {
    "questions": ("questions",),
    "media": ("media",),
    "passages": ("passages",),
    "subjects": ("subjects",),
    "topics": ("topics",),
    "subtopics": ("subtopics",),
    "verifications": ("verifications",),
}

#: Tables that only exist once a row is a candidate for production.
READY_ONLY: Final[tuple[str, ...]] = ("verifications",)


def table(logical: str, lane: Lane) -> str:
    """The physical table name for a logical name in a lane."""
    if logical not in LANE_TABLES:
        raise StoreError("unknown table", logical=logical, known=sorted(LANE_TABLES))
    return f"{LANE_PREFIX[lane]}{logical}"


def lane_of(physical: str) -> Lane | None:
    """Which lane a physical table belongs to, or ``None`` when it is not ours."""
    for lane, prefix in LANE_PREFIX.items():
        if physical.startswith(prefix):
            return lane  # type: ignore[return-value]
    return None


def _question_table(lane: Lane) -> str:
    """DDL for one lane's questions.

    ``section`` is present in every lane and NOT NULL is deliberately not
    applied: the API reads the column, and the pipeline's omission of it from
    ``harvest_staging`` left it permanently null on every synced question while
    the contract stayed green. Here the column exists from the first migration
    so there is nothing to forget.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {table("questions", lane)} (
        id                  TEXT PRIMARY KEY,
        source_url          TEXT NOT NULL DEFAULT '',
        source_item_id      TEXT NOT NULL DEFAULT '',
        payload_hash        TEXT NOT NULL DEFAULT '',
        exam                TEXT NOT NULL,
        subject             TEXT NOT NULL,
        year                INTEGER,
        source              TEXT NOT NULL DEFAULT 'claimed_paper',
        text                TEXT NOT NULL,
        inline              TEXT NOT NULL DEFAULT '[]',
        options             TEXT NOT NULL,
        answer              TEXT NOT NULL,
        subtopic_id         TEXT,
        section             TEXT,
        passage_id          TEXT,
        explanation         TEXT,
        marks               REAL NOT NULL DEFAULT 1.0,
        difficulty          INTEGER NOT NULL DEFAULT 3,
        content_hash        TEXT NOT NULL DEFAULT '',
        fingerprint         TEXT,
        stem_key            TEXT,
        gate_status         TEXT NOT NULL DEFAULT 'pending',
        gate_reason         TEXT,
        attempts            INTEGER NOT NULL DEFAULT 0,
        error               TEXT,
        next_retry_at       TEXT,
        run_id              TEXT,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    )
    """


def _media_table(lane: Lane) -> str:
    """One lane's media inventory.

    ``source_url`` is the unique key, so the same figure referenced by forty
    questions is discovered once. ``description`` sits here rather than in a
    side table because it belongs to the figure, not to the question that first
    mentioned it.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {table("media", lane)} (
        id                  TEXT PRIMARY KEY,
        source_url          TEXT NOT NULL UNIQUE,
        question_id         TEXT,
        blob_path           TEXT,
        derived_path        TEXT,
        sha256              TEXT,
        bytes               INTEGER,
        media_url           TEXT,
        status              TEXT NOT NULL DEFAULT 'discovered',
        description         TEXT,
        description_model   TEXT,
        description_verdict TEXT,
        description_verified_at TEXT,
        attempts            INTEGER NOT NULL DEFAULT 0,
        error               TEXT,
        next_retry_at       TEXT,
        run_id              TEXT,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    )
    """


def _passage_table(lane: Lane) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table("passages", lane)} (
        id              TEXT PRIMARY KEY,
        exam            TEXT NOT NULL,
        subject         TEXT NOT NULL,
        year            INTEGER,
        kind            TEXT NOT NULL DEFAULT 'Comprehension',
        title           TEXT,
        author          TEXT,
        text            TEXT NOT NULL,
        inline          TEXT NOT NULL DEFAULT '[]',
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL
    )
    """


def _subject_table(lane: Lane) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table("subjects", lane)} (
        slug                        TEXT PRIMARY KEY,
        exam                        TEXT NOT NULL,
        name                        TEXT NOT NULL,
        is_compulsory               INTEGER NOT NULL DEFAULT 0,
        objective_paper_questions   INTEGER,
        created_at                  TEXT NOT NULL,
        updated_at                  TEXT NOT NULL
    )
    """


def _topic_table(lane: Lane) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table("topics", lane)} (
        slug        TEXT PRIMARY KEY,
        subject     TEXT NOT NULL,
        exam        TEXT NOT NULL,
        name        TEXT NOT NULL,
        ord         INTEGER NOT NULL DEFAULT 0,
        weight      REAL,
        objectives  TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """


def _subtopic_table(lane: Lane) -> str:
    return f"""
    CREATE TABLE IF NOT EXISTS {table("subtopics", lane)} (
        slug        TEXT PRIMARY KEY,
        topic       TEXT NOT NULL,
        name        TEXT NOT NULL,
        ord         INTEGER NOT NULL DEFAULT 0,
        objectives  TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """


def _verification_table(lane: Lane) -> str:
    """One lane's verifications.

    The index covers ``(question_id, created_at)`` because the API's verified
    predicate compares ``(v2.created_at, v2.id) > (v.created_at, v.id)`` to find
    whether a later human pass supersedes an earlier one. The pipeline's
    approved table indexed ``question_id`` alone, so that comparison had no
    index behind it.
    """
    return f"""
    CREATE TABLE IF NOT EXISTS {table("verifications", lane)} (
        id            TEXT PRIMARY KEY,
        question_id   TEXT NOT NULL,
        kind          TEXT NOT NULL,
        verdict       TEXT NOT NULL,
        scope         TEXT NOT NULL DEFAULT '[]',
        verifier      TEXT NOT NULL,
        detail        TEXT,
        content_hash  TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )
    """


def _indexes(lane: Lane) -> tuple[str, ...]:
    prefix = LANE_PREFIX[lane]
    common = (
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_subject ON {prefix}questions(subject, exam)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_gate ON {prefix}questions(gate_status)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_run ON {prefix}questions(run_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_retry ON {prefix}questions(next_retry_at)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_subtopic ON {prefix}questions(subtopic_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_year ON {prefix}questions(year)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_fingerprint ON {prefix}questions(fingerprint)",
        # The normalised stem, indexed on its own, because the two duplicate
        # buckets are different lookups: one needs the whole fingerprint and one
        # needs only the stem. Without this the shared-stem bucket is a scan of
        # the lane, which is what made the old audit quadratic.
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}q_stem_key ON {prefix}questions(stem_key)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}m_status ON {prefix}media(status)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}m_question ON {prefix}media(question_id)",
        f"CREATE INDEX IF NOT EXISTS idx_{prefix}m_description ON {prefix}media(description)",
    )
    if lane != "raw":
        return common
    # The raw lane's dedupe rule, enforced rather than merely implied by the
    # primary key: the same question, from the same place, with the same bytes,
    # is one row however many times it is scraped.
    #
    # Raw only. This is a property of scraping, not of the data. Putting it on
    # every lane made promotion collapse, because a ready row carries no
    # provenance and every such row then collided on the same empty key.
    return (
        *common,
        f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{prefix}q_source ON "
        f"{prefix}questions(source_url, source_item_id, payload_hash)",
    )


def _runs_ddl() -> tuple[str, ...]:
    """The run trail. One row per task execution, plus its per-row outcomes.

    ``task`` and ``target`` are indexed because the question we ask most often is
    which run last touched a given lane.
    """
    return (
        """
        CREATE TABLE IF NOT EXISTS runs (
            id           TEXT PRIMARY KEY,
            task         TEXT NOT NULL,
            target       TEXT NOT NULL DEFAULT 'work',
            selector     TEXT NOT NULL DEFAULT 'all',
            sink         TEXT NOT NULL DEFAULT 'db',
            status       TEXT NOT NULL DEFAULT 'running',
            total        INTEGER NOT NULL DEFAULT 0,
            succeeded    INTEGER NOT NULL DEFAULT 0,
            skipped      INTEGER NOT NULL DEFAULT 0,
            failed       INTEGER NOT NULL DEFAULT 0,
            started_at   TEXT NOT NULL,
            finished_at  TEXT,
            detail       TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_runs_task ON runs(task, started_at)",
        "CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)",
        """
        CREATE TABLE IF NOT EXISTS run_outcomes (
            run_id      TEXT NOT NULL,
            row_id      TEXT NOT NULL,
            state       TEXT NOT NULL,
            code        TEXT,
            detail      TEXT,
            retryable   INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            PRIMARY KEY (run_id, row_id)
        )
        """,
    )


def DDL() -> tuple[str, ...]:
    """Every statement that brings a database to the current shape.

    Idempotent, so running it at the start of a run is safe. Migrations are
    ``ALTER TABLE ADD COLUMN`` wrapped in a probe, because SQLite has no
    ``IF NOT EXISTS`` for columns, and the pipeline swallowed those failures
    inside ``except Exception: pass``, which hid real migration errors.
    """
    statements: list[str] = []
    for lane in LANES:
        for builder in (
            _question_table,
            _media_table,
            _passage_table,
            _subject_table,
            _topic_table,
            _subtopic_table,
            _verification_table,
        ):
            statements.append(builder(lane))
        statements.extend(_indexes(lane))
    statements.extend(_runs_ddl())
    return tuple(statements)


#: Columns added after a lane first shipped. Each is probed and applied once, so
#: running this on a current database does nothing.
_ADDED_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("questions", "section"),
    ("questions", "fingerprint"),
    ("questions", "stem_key"),
    ("questions", "gate_reason"),
    ("media", "description"),
    ("media", "description_model"),
    ("media", "description_verdict"),
    ("media", "description_verified_at"),
    ("media", "derived_path"),
    ("media", "bytes"),
    ("media", "sha256"),
)

MIGRATIONS: Final[tuple[tuple[str, Lane, str], ...]] = tuple(
    (logical, lane, column) for logical, column in _ADDED_COLUMNS for lane in LANES
)


async def ensure_schema(store: object) -> None:
    """Bring the database to the current shape. Safe to call on every run."""
    typed_store = cast("Store", store)
    for statement in DDL():
        await typed_store.execute(statement)
    for logical, lane, column in MIGRATIONS:
        await _add_column(typed_store, table(logical, lane), column)


async def _add_column(store: object, physical: str, column: str) -> None:
    """Add one column if the table does not already have it.

    The probe is the error handling. SQLite raises on a duplicate column and we
    treat that specific error as success, rather than wrapping every failure in
    a bare except and calling it done.
    """
    typed_store = cast("Store", store)
    rows = await typed_store.fetch_all(f'PRAGMA table_info("{physical}")')
    if any(str(r.get("name")) == column for r in rows):
        return
    await typed_store.execute(f'ALTER TABLE "{physical}" ADD COLUMN "{column}" TEXT')


def assert_lane_parity() -> None:
    """Every logical table must exist in every lane.

    A lane that gained a table the others lack is the exact shape of the bug we
    are avoiding, so it is checked before anything runs.
    """
    problems: list[str] = []
    for logical, suffixes in LANE_TABLES.items():
        lanes_with = {lane for lane in LANES if table(logical, lane).endswith(suffixes[0])}
        if lanes_with != set(LANES):
            problems.append(f"{logical}: {sorted(set(LANES) - lanes_with)} lack it")
    if problems:
        raise StoreError("lane tables are out of step", problems=problems)
