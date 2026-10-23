"""Tests for pipeline storage, DDL, and repository operations."""

import pytest
from pipeline.storage.client import TursoClient
from pipeline.storage.schema import init_pipeline_schema
from pipeline.storage.repository import PipelineRepository


@pytest.fixture
async def repo():
    # In-memory SQLite client
    client = TursoClient(":memory:")
    await init_pipeline_schema(client)
    repo = PipelineRepository(client)
    yield repo
    client.close()


@pytest.mark.asyncio
async def test_schema_init_and_scrape_run(repo: PipelineRepository):
    run_id = "run_test_001"
    await repo.create_scrape_run(
        run_id=run_id,
        source_name="jamb_archive",
        exam="JAMB",
        subject="mathematics",
        year=2025,
    )

    # Verify run exists in DB
    res = await repo.db.execute("SELECT * FROM scrape_runs WHERE id = ?", [run_id])
    assert len(res.rows) == 1
    assert res.rows[0]["status"] == "running"
    assert res.rows[0]["source_name"] == "jamb_archive"

    # Complete the run
    await repo.complete_scrape_run(
        run_id=run_id,
        total_scraped=40,
        valid_admitted=38,
        rejected_gate0=2,
    )

    res_after = await repo.db.execute("SELECT * FROM scrape_runs WHERE id = ?", [run_id])
    assert res_after.rows[0]["status"] == "completed"
    assert res_after.rows[0]["total_scraped"] == 40
    assert res_after.rows[0]["valid_admitted"] == 38
    assert res_after.rows[0]["rejected_gate0"] == 2


@pytest.mark.asyncio
async def test_staging_insertion_and_fingerprint_check(repo: PipelineRepository):
    run_id = "run_test_002"
    await repo.create_scrape_run(run_id, "jamb_archive", "JAMB", "physics", 2025)

    qid = "stage_q_test_1"
    fp = "abc123hashfingerprint"
    options = [
        {"id": "a", "text": "Option A"},
        {"id": "b", "text": "Option B"},
        {"id": "c", "text": "Option C"},
        {"id": "d", "text": "Option D"},
    ]

    # Check not staged
    assert await repo.is_fingerprint_staged(fp) is False

    # Insert staging question
    await repo.insert_staging_question(
        qid=qid,
        run_id=run_id,
        source_name="jamb_archive",
        source_url="https://example.com/q1",
        source_item_id="item_001",
        exam="JAMB",
        subject="physics",
        year=2025,
        stem_raw="A particle moves with uniform acceleration. Calculate its displacement.",
        options_raw=options,
        answer_raw="a",
        fingerprint=fp,
        gate0_status="valid",
    )

    # Now staged
    assert await repo.is_fingerprint_staged(fp) is True

    # Fetch pending
    pending = await repo.get_pending_ai_questions("physics", "JAMB", limit=10)
    assert len(pending) == 1
    assert pending[0]["id"] == qid
    assert pending[0]["pipeline_status"] == "validated"


@pytest.mark.asyncio
async def test_ai_results_update_and_review_queue(repo: PipelineRepository):
    run_id = "run_test_003"
    await repo.create_scrape_run(run_id, "jamb_archive", "JAMB", "chemistry", 2025)

    qid = "stage_q_chem_1"
    fp = "chem_fp_123"
    await repo.insert_staging_question(
        qid=qid,
        run_id=run_id,
        source_name="jamb_archive",
        source_url=None,
        source_item_id="chem_1",
        exam="JAMB",
        subject="chemistry",
        year=2025,
        stem_raw="Which gas is produced when magnesium reacts with steam?",
        options_raw=[{"id": "a", "text": "Hydrogen"}, {"id": "b", "text": "Oxygen"}, {"id": "c", "text": "Nitrogen"}, {"id": "d", "text": "Chlorine"}],
        answer_raw="a",
        fingerprint=fp,
        gate0_status="valid",
    )

    # Simulate AI evaluation with disagreement (triggers review queue)
    await repo.update_ai_results(
        question_id=qid,
        proposed_topic="metals-and-their-compounds",
        proposed_subtopic="reaction-of-metals-with-water",
        answer_verdict="DISAGREEMENT",
        explanation_quality="GOOD",
        proposed_explanation={"key_point": "Magnesium reacts with steam to form MgO and H2.", "body": "Mg + H2O -> MgO + H2"},
        confidence=0.72,
    )

    # Flag in review queue
    await repo.add_to_review_queue(
        question_id=qid,
        subject="chemistry",
        exam="JAMB",
        flag_reason="answer_mismatch",
        priority=1,
    )

    review_items = await repo.get_review_queue("open")
    assert len(review_items) == 1
    assert review_items[0]["question_id"] == qid
    assert review_items[0]["flag_reason"] == "answer_mismatch"
