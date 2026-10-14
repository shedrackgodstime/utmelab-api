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


@pytest.mark.asyncio
async def test_promoter_image_positions_and_audit_report():
    pipe_client = TursoClient(":memory:")
    await init_pipeline_schema(pipe_client)

    promoter = PipelinePromoter(pipe_client)

    # 1. Stem mentioning "below"
    stem_below = "In the electric circuit shown below, determine the total resistance."
    staging_row_below = {
        "id": "stage_q_img_below",
        "exam": "JAMB",
        "subject": "physics",
        "year": 2025,
        "stem_raw": stem_below,
        "options_raw": json.dumps([
            {"id": "a", "text": "5 ohms"},
            {"id": "b", "text": "10 ohms"},
            {"id": "c", "text": "15 ohms"},
            {"id": "d", "text": "20 ohms"},
        ]),
        "answer_raw": "b",
        "media_url": "http://example.com/resistor_circuit.png",
        "audit_report": "Diagram clearly displays two 20-ohm resistors in parallel; net resistance verified as 10 ohms.",
    }

    qid_below = await promoter.promote(
        staging_row=staging_row_below,
        subtopic_id="electric-circuits",
    )

    q_res = await pipe_client.execute("SELECT * FROM approved_questions WHERE id = ?", [qid_below])
    assert len(q_res.rows) == 1
    row = q_res.rows[0]
    inline = json.loads(row["inline"])
    assert len(inline) == 1
    assert inline[0]["kind"] == "image"
    assert inline[0]["position"] == "below"
    assert inline[0]["start"] == len(stem_below)
    assert inline[0]["len"] == 0
    assert inline[0]["url"] == "https://example.com/resistor_circuit.png"
    assert row["audit_report"] == staging_row_below["audit_report"]

    # 2. Stem with "above" / default
    stem_above = "Study the diagram above to find the focal length of the mirror."
    staging_row_above = {
        "id": "stage_q_img_above",
        "exam": "JAMB",
        "subject": "physics",
        "year": 2025,
        "stem_raw": stem_above,
        "options_raw": json.dumps([
            {"id": "a", "text": "10 cm"},
            {"id": "b", "text": "20 cm"},
            {"id": "c", "text": "30 cm"},
            {"id": "d", "text": "40 cm"},
        ]),
        "answer_raw": "a",
        "media_url": "https://example.com/concave_mirror.png",
        "audit_report": "Mirror diagram shows center of curvature at 20 cm, yielding focal length f = R/2 = 10 cm.",
    }

    qid_above = await promoter.promote(
        staging_row=staging_row_above,
        subtopic_id="reflection-at-curved-surfaces",
    )

    q_res_above = await pipe_client.execute("SELECT * FROM approved_questions WHERE id = ?", [qid_above])
    row_above = q_res_above.rows[0]
    inline_above = json.loads(row_above["inline"])
    assert len(inline_above) == 1
    assert inline_above[0]["kind"] == "image"
    assert inline_above[0]["position"] == "above"
    assert inline_above[0]["start"] == 0
    assert inline_above[0]["len"] == 0
    assert row_above["audit_report"] == staging_row_above["audit_report"]

    pipe_client.close()

