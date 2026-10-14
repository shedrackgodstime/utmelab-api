"""DDL and schema initializers for the dedicated Pipeline Turso database."""

from typing import List
from pipeline.storage.client import TursoClient

PIPELINE_DDL: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS scrape_runs (
        id TEXT PRIMARY KEY,
        source_name TEXT NOT NULL,
        exam TEXT NOT NULL,
        subject TEXT NOT NULL,
        year INTEGER,
        status TEXT NOT NULL,
        total_scraped INTEGER DEFAULT 0,
        valid_admitted INTEGER DEFAULT 0,
        rejected_gate0 INTEGER DEFAULT 0,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        error_summary TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS harvest_staging (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT,
        source_item_id TEXT,
        exam TEXT NOT NULL,
        subject TEXT NOT NULL,
        year INTEGER NOT NULL,
        stem_raw TEXT NOT NULL,
        options_raw TEXT NOT NULL,
        answer_raw TEXT NOT NULL,
        explanation_raw TEXT,
        media_url TEXT,
        fingerprint TEXT NOT NULL UNIQUE,
        gate0_status TEXT NOT NULL,
        gate0_rejection_reason TEXT,
        ai_status TEXT NOT NULL,
        proposed_topic TEXT,
        proposed_subtopic TEXT,
        answer_check_verdict TEXT,
        explanation_quality TEXT,
        proposed_explanation TEXT,
        ai_confidence REAL,
        detected_marks TEXT,
        ai_raw_response TEXT,
        pipeline_status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES scrape_runs(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_staging_fingerprint ON harvest_staging(fingerprint);",
    "CREATE INDEX IF NOT EXISTS idx_staging_subject_status ON harvest_staging(subject, pipeline_status);",
    "CREATE INDEX IF NOT EXISTS idx_staging_ai_status ON harvest_staging(ai_status);",
    """
    CREATE TABLE IF NOT EXISTS review_queue (
        question_id TEXT PRIMARY KEY,
        subject TEXT NOT NULL,
        exam TEXT NOT NULL,
        flag_reason TEXT NOT NULL,
        priority INTEGER DEFAULT 1,
        reviewer TEXT,
        review_status TEXT NOT NULL,
        resolution_notes TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        FOREIGN KEY(question_id) REFERENCES harvest_staging(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_review_status_prio ON review_queue(review_status, priority);",
    """
    CREATE TABLE IF NOT EXISTS approved_questions (
        id TEXT PRIMARY KEY,
        staging_id TEXT NOT NULL,
        exam TEXT NOT NULL,
        subject TEXT NOT NULL,
        year INTEGER NOT NULL,
        source TEXT NOT NULL,
        text TEXT NOT NULL,
        inline TEXT NOT NULL DEFAULT '[]',
        options TEXT NOT NULL,
        answer TEXT NOT NULL,
        subtopic_id TEXT,
        section TEXT,
        passage_id TEXT,
        explanation TEXT,
        marks REAL NOT NULL,
        difficulty INTEGER NOT NULL,
        content_hash TEXT NOT NULL,
        approved_at TEXT NOT NULL,
        FOREIGN KEY(staging_id) REFERENCES harvest_staging(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_approved_exam_subj ON approved_questions(exam, subject);",
    """
    CREATE TABLE IF NOT EXISTS approved_verifications (
        id TEXT PRIMARY KEY,
        question_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        verdict TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT '[]',
        verifier TEXT NOT NULL,
        detail TEXT,
        content_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(question_id) REFERENCES approved_questions(id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_appr_ver_q ON approved_verifications(question_id);"
]


async def init_pipeline_schema(client: TursoClient) -> None:
    """Initializes all tables and indexes in the pipeline database."""
    for statement in PIPELINE_DDL:
        clean_stmt = statement.strip()
        if clean_stmt:
            await client.execute(clean_stmt)
