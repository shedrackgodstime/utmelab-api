"""Unit tests for ProductionSyncEngine."""

import json
import pytest
from pipeline.orchestrator.promoter import compute_content_hash, to_rich_text
from pipeline.orchestrator.sync_prod import ProductionSyncEngine
from pipeline.storage.client import TursoClient
from pipeline.storage.schema import init_pipeline_schema


@pytest.fixture
async def setup_clients():
    pipe_client = TursoClient(":memory:")
    await init_pipeline_schema(pipe_client)

    # In-memory mock for production DB
    prod_client = TursoClient(":memory:")
    await prod_client.execute(
        "CREATE TABLE topics (slug TEXT PRIMARY KEY, subject TEXT, exam TEXT, name TEXT, \"order\" INTEGER, weight INTEGER, objectives TEXT)"
    )
    await prod_client.execute(
        "CREATE TABLE subtopics (slug TEXT PRIMARY KEY, topic TEXT, name TEXT, \"order\" INTEGER, objectives TEXT)"
    )
    await prod_client.execute(
        "CREATE TABLE passages (id TEXT PRIMARY KEY, exam TEXT, subject TEXT, year INTEGER, kind TEXT, title TEXT, author TEXT, text TEXT, inline TEXT)"
    )
    await prod_client.execute(
        "CREATE TABLE questions (id TEXT PRIMARY KEY, exam TEXT, subject TEXT, year INTEGER, source TEXT, text TEXT, inline TEXT, options TEXT, answer TEXT, subtopic_id TEXT, section TEXT, passage_id TEXT, explanation TEXT, marks REAL, difficulty INTEGER, content_hash TEXT)"
    )

    # Seed authoritative production subtopic
    await prod_client.execute(
        "INSERT INTO subtopics (slug, topic, name, \"order\", objectives) VALUES ('newtons-laws', 'mechanics', 'Newton Laws', 1, '[]')"
    )

    yield pipe_client, prod_client

    pipe_client.close()
    prod_client.close()


@pytest.mark.asyncio
async def test_sync_prod_dry_run_and_commit(setup_clients):
    pipe_client, prod_client = setup_clients

    # 1. Create a valid approved question with matching verification in Pipeline DB
    stem_rich = to_rich_text("State Newton's first law of motion.", [])
    options = [
        {"id": "a", "text": to_rich_text("An object stays at rest unless acted on by force.")},
        {"id": "b", "text": to_rich_text("F = ma")},
    ]
    answer = "a"
    content_hash = compute_content_hash(stem_rich, options, answer, None)

    await pipe_client.execute(
        """
        INSERT INTO approved_questions (
            id, staging_id, exam, subject, year, source, text, inline, options, answer,
            subtopic_id, section, passage_id, explanation, marks, difficulty, content_hash, approved_at
        ) VALUES (
            'q_phys_001', 'stage_phys_001', 'JAMB', 'physics', 2025, 'claimed_paper', ?, '[]', ?, ?,
            'newtons-laws', NULL, NULL, NULL, 2.5, 2, ?, '2026-10-15T00:00:00Z'
        )
        """,
        [stem_rich["text"], json.dumps(options), answer, content_hash],
    )

    await pipe_client.execute(
        """
        INSERT INTO approved_verifications (
            id, question_id, kind, verdict, scope, verifier, content_hash, created_at
        ) VALUES (
            'v_phys_001', 'q_phys_001', 'ai_bulk', 'pass', '[]', 'opencode', ?, '2026-10-15T00:00:00Z'
        )
        """,
        [content_hash],
    )

    engine = ProductionSyncEngine(pipe_client, prod_client)

    # 2. Test Dry Run: should validate 100% but write 0 rows to prod
    dry_res = await engine.validate_and_sync(dry_run=True)
    assert dry_res["dry_run"] is True
    assert dry_res["total_candidates"] == 1
    assert dry_res["validated_pass"] == 1
    assert len(dry_res["validation_failures"]) == 0
    assert dry_res["questions_synced"] == 0

    # Verify prod table is still empty
    check_prod = await prod_client.execute("SELECT count(*) as cnt FROM questions")
    assert check_prod.rows[0]["cnt"] == 0

    # 3. Test Live Commit (dry_run=False)
    live_res = await engine.validate_and_sync(dry_run=False)
    assert live_res["dry_run"] is False
    assert live_res["validated_pass"] == 1
    assert live_res["questions_synced"] == 1

    # Verify row now exists in prod questions table with matching columns
    prod_rows = await prod_client.execute("SELECT * FROM questions WHERE id = 'q_phys_001'")
    assert len(prod_rows.rows) == 1
    assert prod_rows.rows[0]["content_hash"] == content_hash
    assert prod_rows.rows[0]["subtopic_id"] == "newtons-laws"


@pytest.mark.asyncio
async def test_sync_prod_rejects_dangling_subtopic(setup_clients):
    pipe_client, prod_client = setup_clients

    stem_rich = to_rich_text("Some question stem", [])
    options = [{"id": "a", "text": to_rich_text("opt a")}]
    answer = "a"
    content_hash = compute_content_hash(stem_rich, options, answer, None)

    # Insert with a non-existent subtopic
    await pipe_client.execute(
        """
        INSERT INTO approved_questions (
            id, staging_id, exam, subject, year, source, text, inline, options, answer,
            subtopic_id, section, passage_id, explanation, marks, difficulty, content_hash, approved_at
        ) VALUES (
            'q_bad_subtopic', 'stage_bad', 'JAMB', 'physics', 2025, 'claimed_paper', ?, '[]', ?, ?,
            'non-existent-subtopic-slug', NULL, NULL, NULL, 2.5, 2, ?, '2026-10-15T00:00:00Z'
        )
        """,
        [stem_rich["text"], json.dumps(options), answer, content_hash],
    )
    await pipe_client.execute(
        """
        INSERT INTO approved_verifications (
            id, question_id, kind, verdict, scope, verifier, content_hash, created_at
        ) VALUES (
            'v_bad', 'q_bad_subtopic', 'ai_bulk', 'pass', '[]', 'opencode', ?, '2026-10-15T00:00:00Z'
        )
        """,
        [content_hash],
    )

    engine = ProductionSyncEngine(pipe_client, prod_client)
    res = await engine.validate_and_sync(dry_run=False)

    # Should fail validation and refuse to write to prod
    assert res["validated_pass"] == 0
    assert len(res["validation_failures"]) == 1
    assert "not found in production subtopics catalog" in res["validation_failures"][0]["errors"][0]
    assert res["questions_synced"] == 0
