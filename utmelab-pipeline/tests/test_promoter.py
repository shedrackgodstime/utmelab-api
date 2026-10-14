"""Tests for promotion engine and content hash."""

import json
import pytest
from pipeline.orchestrator.promoter import PipelinePromoter, compute_content_hash, to_rich_text
from pipeline.storage.client import TursoClient
from pipeline.storage.schema import init_pipeline_schema


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
async def test_promoter_writes_only_to_pipeline_approved_tables():
    # In-memory client representing dedicated pipeline DB
    pipe_client = TursoClient(":memory:")
    await init_pipeline_schema(pipe_client)

    # Insert a dummy staging row
    staging_id = "stage_q_12345"
    await pipe_client.execute(
        """
        INSERT INTO scrape_runs (id, source_name, exam, subject, year, status, started_at)
        VALUES ('run_1', 'jamb', 'JAMB', 'physics', 2025, 'running', '2026-10-14T00:00:00Z')
        """
    )
    await pipe_client.execute(
        """
        INSERT INTO harvest_staging (
            id, run_id, source_name, exam, subject, year, stem_raw, options_raw, answer_raw,
            fingerprint, gate0_status, ai_status, pipeline_status, created_at, updated_at
        ) VALUES (
            ?, 'run_1', 'jamb', 'JAMB', 'physics', 2025, 'What is the unit of capacitance?',
            ?, 'a', 'fp_123', 'valid', 'completed', 'auto_approved', '2026-10-14T00:00:00Z', '2026-10-14T00:00:00Z'
        )
        """,
        [
            staging_id,
            json.dumps([
                {"id": "a", "text": "Farad"},
                {"id": "b", "text": "Henry"},
                {"id": "c", "text": "Coulomb"},
                {"id": "d", "text": "Ohm"},
            ]),
        ],
    )

    promoter = PipelinePromoter(pipe_client)
    staging_row = {
        "id": staging_id,
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

    # 1. Verify row in approved_questions in Pipeline DB
    q_res = await pipe_client.execute("SELECT * FROM approved_questions WHERE id = ?", [promoted_id])
    assert len(q_res.rows) == 1
    assert q_res.rows[0]["answer"] == "a"
    assert q_res.rows[0]["subtopic_id"] == "capacitors-and-capacitance"
    assert q_res.rows[0]["staging_id"] == staging_id

    # 2. Verify row in approved_verifications in Pipeline DB
    v_res = await pipe_client.execute("SELECT * FROM approved_verifications WHERE question_id = ?", [promoted_id])
    assert len(v_res.rows) == 1
    assert v_res.rows[0]["verdict"] == "pass"

    # 3. Verify staging status updated to approved_for_prod
    s_res = await pipe_client.execute("SELECT pipeline_status FROM harvest_staging WHERE id = ?", [staging_id])
    assert s_res.rows[0]["pipeline_status"] == "approved_for_prod"

    pipe_client.close()
