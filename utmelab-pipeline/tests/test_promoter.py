"""Tests for promotion engine and content hash."""

import json
import pytest
from pipeline.orchestrator.promoter import ProductionPromoter, compute_content_hash, to_rich_text
from pipeline.storage.client import TursoClient


def test_compute_content_hash_deterministic():
    stem = "Calculate the energy of a photon of frequency 5 x 10^14 Hz."
    options = [
        {"id": "a", "text": "3.3 x 10^-19 J"},
        {"id": "b", "text": "2.1 x 10^-19 J"},
        {"id": "c", "text": "1.5 x 10^-19 J"},
        {"id": "d", "text": "4.2 x 10^-19 J"},
    ]
    h1 = compute_content_hash(stem, options, "a")
    h2 = compute_content_hash(stem, options, "a")
    assert h1 == h2
    assert len(h1) == 64


@pytest.mark.asyncio
async def test_promoter_writes_to_production():
    # In-memory client representing production DB
    prod_client = TursoClient(":memory:")
    # Initialize basic schema matching production
    await prod_client.execute("""
    CREATE TABLE questions (
        id TEXT PRIMARY KEY, exam TEXT NOT NULL, subject TEXT NOT NULL, year INTEGER NOT NULL,
        source TEXT NOT NULL, text TEXT NOT NULL, inline TEXT NOT NULL, options TEXT NOT NULL,
        answer TEXT NOT NULL, subtopic_id TEXT, section TEXT, passage_id TEXT,
        explanation TEXT, marks REAL NOT NULL, difficulty INTEGER NOT NULL, content_hash TEXT NOT NULL
    );
    """)
    await prod_client.execute("""
    CREATE TABLE verifications (
        id TEXT PRIMARY KEY, question_id TEXT NOT NULL, kind TEXT NOT NULL, verdict TEXT NOT NULL,
        scope TEXT NOT NULL, verifier TEXT NOT NULL, detail TEXT, content_hash TEXT NOT NULL, created_at TEXT NOT NULL
    );
    """)

    promoter = ProductionPromoter(prod_client)
    staging_row = {
        "id": "stage_q_12345",
        "exam": "JAMB",
        "subject": "physics",
        "year": 2025,
        "stem_raw": "What is the unit of capacitance?",
        "options_raw": json.dumps([
            {"id": "a", "text": "Farad"},
            {"id": "b", "text": "Henry"},
            {"id": "c", "text": "Coulomb"},
            {"id": "d", "text": "Ohm"},
        ]),
        "answer_raw": "a",
        "proposed_explanation": json.dumps({
            "key_point": "Capacitance is measured in Farads (F).",
            "body": "C = Q / V, where 1 Farad = 1 Coulomb per Volt.",
            "trap": "Henry is inductance, Coulomb is charge."
        }),
    }

    promoted_id = await promoter.promote(
        staging_row=staging_row,
        subtopic_id="capacitors-and-capacitance",
    )

    assert promoted_id == "q_12345"

    # Verify row in questions table
    q_res = await prod_client.execute("SELECT * FROM questions WHERE id = ?", [promoted_id])
    assert len(q_res.rows) == 1
    assert q_res.rows[0]["answer"] == "a"
    assert q_res.rows[0]["subtopic_id"] == "capacitors-and-capacitance"

    # Verify row in verifications table
    v_res = await prod_client.execute("SELECT * FROM verifications WHERE question_id = ?", [promoted_id])
    assert len(v_res.rows) == 1
    assert v_res.rows[0]["verdict"] == "pass"

    prod_client.close()
