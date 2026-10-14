"""Unit tests for MetricsCollector and dashboard renderers."""

import pytest
from pipeline.metrics.collector import MetricsCollector
from pipeline.storage.client import TursoClient
from pipeline.storage.schema import init_pipeline_schema


@pytest.fixture
async def pipe_client():
    client = TursoClient(":memory:")
    await init_pipeline_schema(client)
    yield client
    client.close()


@pytest.mark.asyncio
async def test_collector_empty_database(pipe_client: TursoClient):
    collector = MetricsCollector(pipe_client)
    metrics = await collector.collect()

    assert metrics["health"]["status"] == "HEALTHY"
    assert metrics["funnel"]["total_staged"] == 0
    assert metrics["funnel"]["gate0_pass_rate_pct"] == 0.0
    assert metrics["funnel"]["ai_processed"] == 0
    assert metrics["funnel"]["approved_questions_total"] == 0
    assert metrics["review_queue"]["open"] == 0

    cli_text = collector.render_cli_dashboard(metrics)
    assert "UTMELAB CBT PIPELINE OBSERVABILITY DASHBOARD" in cli_text
    assert "CONVERSION FUNNEL" in cli_text

    md_text = collector.render_markdown_summary(metrics)
    assert "## 📊 UTME Lab Pipeline Telemetry Report" in md_text
    assert "| **Total Staged** | `0` |" in md_text


@pytest.mark.asyncio
async def test_collector_populated_database(pipe_client: TursoClient):
    # Insert scrape run
    await pipe_client.execute(
        """
        INSERT INTO scrape_runs (id, source_name, exam, subject, year, status, total_scraped, valid_admitted, rejected_gate0, started_at)
        VALUES ('run_1', 'jamb_myschool', 'JAMB', 'physics', 2025, 'completed', 10, 8, 2, '2026-10-15T00:00:00Z')
        """
    )

    # Insert 2 staged rows: 1 valid and auto_approved, 1 rejected
    await pipe_client.execute(
        """
        INSERT INTO harvest_staging (
            id, run_id, source_name, exam, subject, year, stem_raw, options_raw, answer_raw,
            fingerprint, gate0_status, gate0_rejection_reason, ai_status, pipeline_status,
            ai_confidence, answer_check_verdict, media_url, created_at, updated_at
        ) VALUES (
            'stage_1', 'run_1', 'jamb_myschool', 'JAMB', 'physics', 2025, 'What is velocity?',
            '[]', 'a', 'fp_1', 'valid', NULL, 'evaluated', 'auto_approved',
            0.98, 'VERIFIED', 'https://example.com/fig1.png', '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z'
        )
        """
    )
    await pipe_client.execute(
        """
        INSERT INTO harvest_staging (
            id, run_id, source_name, exam, subject, year, stem_raw, options_raw, answer_raw,
            fingerprint, gate0_status, gate0_rejection_reason, ai_status, pipeline_status,
            ai_confidence, answer_check_verdict, media_url, created_at, updated_at
        ) VALUES (
            'stage_2', 'run_1', 'jamb_myschool', 'JAMB', 'physics', 2025, 'Too short',
            '[]', 'a', 'fp_2', 'rejected', 'Stem too short (min 15 chars)', 'pending', 'rejected',
            NULL, NULL, NULL, '2026-10-15T00:00:00Z', '2026-10-15T00:00:00Z'
        )
        """
    )

    # Insert 1 approved question
    await pipe_client.execute(
        """
        INSERT INTO approved_questions (
            id, staging_id, exam, subject, year, source, text, inline, options, answer,
            marks, difficulty, content_hash, approved_at
        ) VALUES (
            'q_1', 'stage_1', 'JAMB', 'physics', 2025, 'claimed_paper', 'What is velocity?',
            '[]', '[]', 'a', 2.5, 2, 'hash_123', '2026-10-15T00:00:00Z'
        )
        """
    )

    collector = MetricsCollector(pipe_client)
    metrics = await collector.collect(subject="physics")

    assert metrics["funnel"]["total_staged"] == 2
    assert metrics["funnel"]["gate0_valid"] == 1
    assert metrics["funnel"]["gate0_rejected"] == 1
    assert metrics["funnel"]["gate0_pass_rate_pct"] == 50.0
    assert metrics["funnel"]["ai_processed"] == 1
    assert metrics["funnel"]["approved_questions_total"] == 1
    assert metrics["ai_telemetry"]["avg_confidence"] == 0.98
    assert metrics["ai_telemetry"]["verdicts"]["verified"] == 1
    assert metrics["ai_telemetry"]["multimodal"]["questions_with_media"] == 1
    assert len(metrics["gate0_rejections"]) == 1
    assert metrics["gate0_rejections"][0]["reason"] == "Stem too short (min 15 chars)"

    cli_text = collector.render_cli_dashboard(metrics)
    assert "physics" in cli_text
    assert "Stem too short" in cli_text

    md_text = collector.render_markdown_summary(metrics)
    assert "physics" in md_text
    assert "| `Stem too short (min 15 chars)` | `1` |" in md_text
