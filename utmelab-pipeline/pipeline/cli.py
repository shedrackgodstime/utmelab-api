"""CLI entry point for utmelab-pipeline."""

import asyncio
from datetime import datetime, timezone
import json
from typing import Optional
import uuid
import click
from pipeline.config import config
from pipeline.gates.mechanical import validate_gate0
from pipeline.orchestrator.worker import BatchProcessor
from pipeline.sources import get_harvester, list_harvesters
from pipeline.storage.client import TursoClient
from pipeline.storage.repository import PipelineRepository
from pipeline.storage.schema import init_pipeline_schema


def get_clients():
    pipe_client = TursoClient(config.pipeline_db_url, config.pipeline_db_token)
    prod_client = (
        TursoClient(config.prod_db_url, config.prod_db_token)
        if config.prod_db_url
        else None
    )
    return pipe_client, prod_client


@click.group()
def main():
    """UTME Lab Pipeline CLI - Ingestion, Validation, and AI Verification."""
    pass


# ── DB SUBCOMMANDS ─────────────────────────────────────────────────────────

@main.group()
def db():
    """Database administration commands."""
    pass


@db.command("init")
@click.option("--db-url", default=None, help="Turso / SQLite DB URL (defaults to config)")
@click.option("--db-token", default=None, help="Turso DB auth token (defaults to config)")
def init_db_cmd(db_url: str, db_token: str):
    """Initializes the pipeline database tables and indexes."""
    url = db_url or config.pipeline_db_url
    token = db_token or config.pipeline_db_token

    if not url:
        click.echo("Error: TURSO_PIPELINE_DB_URL is not set.", err=True)
        raise SystemExit(1)

    async def _init():
        client = TursoClient(url, token)
        click.echo(f"Initializing pipeline schema at {url}...")
        await init_pipeline_schema(client)
        click.echo("Pipeline schema successfully initialized.")
        client.close()

    asyncio.run(_init())


# ── HARVEST COMMAND ────────────────────────────────────────────────────────

@main.command("harvest")
@click.option("--source", "-s", default="jamb", help=f"Harvester source ({', '.join(list_harvesters())})")
@click.option("--subject", required=True, help="Subject slug (e.g. physics, mathematics)")
@click.option("--year", "-y", default=2025, type=int, help="Cohort year")
@click.option("--limit", "-n", default=None, type=int, help="Maximum questions to harvest")
@click.option("--delay", default=1.5, type=float, help="Delay between requests in seconds")
def harvest_cmd(source: str, subject: str, year: int, limit: int, delay: float):
    """Harvests questions from an external source through Gate 0 into the Pipeline DB."""
    pipe_client, prod_client = get_clients()
    repo = PipelineRepository(pipe_client, prod_client)
    harvester = get_harvester(source, delay_seconds=delay)

    run_id = f"run_{source}_{subject}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    async def _run():
        click.echo(f"Starting harvest run: {run_id}")
        click.echo(f"Source: {source} | Subject: {subject} | Year: {year}")

        exam = harvester.supported_exams[0]
        await repo.create_scrape_run(run_id, source, exam, subject, year)

        total, admitted, rejected = 0, 0, 0

        async for q in harvester.crawl(subject=subject, year=year, limit=limit):
            total += 1
            raw_opts = [{"id": o.id, "text": o.text} for o in q.options]

            # Gate 0 Mechanical Validation
            gate_res = validate_gate0(
                stem=q.stem,
                options=raw_opts,
                reported_answer=q.reported_answer,
                exam=q.exam,
                media_url=q.media_url,
            )

            # Check deduplication
            if await repo.is_fingerprint_staged(gate_res.fingerprint):
                click.echo(f"  [DUP] {q.source_item_id}: Stem already staged. Skipping.")
                continue

            qid = f"stage_q_{gate_res.fingerprint[:16]}"
            gate_status = "valid" if gate_res.is_valid else "rejected"

            await repo.insert_staging_question(
                qid=qid,
                run_id=run_id,
                source_name=source,
                source_url=q.source_url,
                source_item_id=q.source_item_id,
                exam=q.exam,
                subject=subject,
                year=year,
                stem_raw=q.stem,
                options_raw=raw_opts,
                answer_raw=q.reported_answer,
                fingerprint=gate_res.fingerprint,
                gate0_status=gate_status,
                gate0_rejection_reason=gate_res.rejection_reason,
                explanation_raw=q.reported_explanation,
                media_url=q.media_url,
            )

            if gate_res.is_valid:
                admitted += 1
                click.echo(f"  [OK] {q.source_item_id} -> {qid}")
            else:
                rejected += 1
                click.echo(f"  [REJECT] {q.source_item_id} -> {gate_res.rejection_reason}")

        await repo.complete_scrape_run(run_id, total, admitted, rejected)
        click.echo(f"\nHarvest completed: {total} scraped, {admitted} admitted, {rejected} rejected.")
        pipe_client.close()
        if prod_client:
            prod_client.close()

    asyncio.run(_run())


# ── AI PROCESS COMMAND ─────────────────────────────────────────────────────

@main.command("process")
@click.option("--subject", required=True, help="Subject to process")
@click.option("--exam", default="JAMB", help="Exam body (JAMB, WAEC)")
@click.option("--limit", "-n", default=50, type=int, help="Batch limit")
@click.option("--concurrency", "-c", default=4, type=int, help="Parallel worker concurrency")
@click.option("--auto-promote", is_flag=True, default=False, help="Automatically promote verified rows to production")
def process_cmd(subject: str, exam: str, limit: int, concurrency: int, auto_promote: bool):
    """Processes staged questions using OpenCode multimodal AI."""
    pipe_client, prod_client = get_clients()
    repo = PipelineRepository(pipe_client, prod_client)
    processor = BatchProcessor(repo)

    async def _process():
        click.echo(f"Processing staging queue: Subject={subject}, Exam={exam}, Limit={limit}, Concurrency={concurrency}")
        stats = await processor.process_subject(
            subject=subject,
            exam=exam,
            limit=limit,
            concurrency=concurrency,
            auto_promote=auto_promote,
        )
        click.echo("\n=== Batch Processing Results ===")
        click.echo(f"Total Processed: {stats['total_processed']}")
        click.echo(f"Answer Verified: {stats['verified']}")
        click.echo(f"Flagged Discrepancies: {stats['discrepancies']}")
        click.echo(f"Promoted to Production: {stats['promoted']}")
        click.echo(f"Processing Errors: {stats['errors']}")

        pipe_client.close()
        if prod_client:
            prod_client.close()

    asyncio.run(_process())


# ── REVIEW QUEUE COMMANDS ──────────────────────────────────────────────────

@main.group()
def review():
    """Commands for inspecting and triaging the exception review queue."""
    pass


@review.command("list")
@click.option("--status", default="open", help="Status filter: open, resolved, discarded")
@click.option("--limit", default=20, type=int, help="Number of items to show")
def list_review_cmd(status: str, limit: int):
    """Lists flagged questions awaiting review."""
    pipe_client, _ = get_clients()
    repo = PipelineRepository(pipe_client)

    async def _list():
        items = await repo.get_review_queue(status=status, limit=limit)
        if not items:
            click.echo(f"No review items found with status '{status}'.")
            return

        click.echo(f"=== Review Queue ({len(items)} items) ===\n")
        for idx, item in enumerate(items, 1):
            click.echo(f"{idx}. [{item['question_id']}] Subject: {item['subject']} | Reason: {item['flag_reason']}")
            click.echo(f"   Stem: {item['stem_raw'][:90]}...")
            click.echo(f"   Recorded Answer: {item['answer_raw']} | AI Verdict: {item.get('answer_check_verdict')}")
            click.echo(f"   Proposed Subtopic: {item.get('proposed_subtopic')}\n")
        pipe_client.close()

    asyncio.run(_list())


# ── STATUS COMMAND ─────────────────────────────────────────────────────────

# ── PROMOTE COMMAND ────────────────────────────────────────────────────────

@main.command("promote")
@click.option("--subject", default=None, help="Subject filter (optional)")
@click.option("--limit", "-n", default=50, type=int, help="Maximum questions to approve")
@click.option("--dry-run", is_flag=True, default=False, help="Preview approval without writing to database")
def promote_cmd(subject: Optional[str], limit: int, dry_run: bool):
    """Promotes auto_approved staging questions into Pipeline DB approved tables (strictly writes to pipeline DB, never to production)."""
    from pipeline.orchestrator.promoter import PipelinePromoter
    pipe_client, _ = get_clients()

    promoter = PipelinePromoter(pipe_client)

    async def _promote():
        where_clauses = ["pipeline_status = 'auto_approved'"]
        params = []
        if subject:
            where_clauses.append("subject = ?")
            params.append(subject)

        sql = f"SELECT * FROM harvest_staging WHERE {' AND '.join(where_clauses)} LIMIT ?"
        params.append(limit)

        res = await pipe_client.execute(sql, params)
        rows = res.rows
        if not rows:
            click.echo("No auto_approved questions found for approval.")
            return

        click.echo(f"Found {len(rows)} auto_approved questions ready for approval.")
        promoted_count = 0

        for r in rows:
            qid = r["id"]
            subtopic = r["proposed_subtopic"]
            marks_raw = r.get("detected_marks")
            marks = json.loads(marks_raw) if marks_raw else []

            if dry_run:
                click.echo(f"  [DRY-RUN] Would approve {qid} -> subject: {r['subject']} | subtopic: {subtopic}")
                promoted_count += 1
            else:
                promoted_id = await promoter.promote(
                    staging_row=r,
                    subtopic_id=subtopic,
                    detected_marks=marks,
                    audit_report=r.get("audit_report"),
                )
                click.echo(f"  [APPROVED] {qid} -> {promoted_id} in approved_questions (Pipeline DB)")
                promoted_count += 1

        click.echo(f"\nApproval completed: {promoted_count} questions {'previewed' if dry_run else 'approved in Pipeline DB'}.")
        pipe_client.close()

    asyncio.run(_promote())


@main.command("status")
def status_cmd():
    """Displays pipeline staging, approved questions, and queue statistics."""
    pipe_client, _ = get_clients()

    async def _status():
        runs = await pipe_client.execute("SELECT COUNT(*) as cnt FROM scrape_runs")
        staging = await pipe_client.execute("SELECT pipeline_status, COUNT(*) as cnt FROM harvest_staging GROUP BY pipeline_status")
        review = await pipe_client.execute("SELECT COUNT(*) as cnt FROM review_queue WHERE review_status = 'open'")
        approved = await pipe_client.execute("SELECT COUNT(*) as cnt FROM approved_questions")

        click.echo("=== Pipeline Status ===")
        click.echo(f"Scrape Runs: {runs.rows[0]['cnt'] if runs.rows else 0}")
        click.echo(f"Approved for Production Review: {approved.rows[0]['cnt'] if approved.rows else 0}")
        click.echo(f"Open Exception Review Queue: {review.rows[0]['cnt'] if review.rows else 0}")
        click.echo("\nStaging Breakdown:")
        for row in staging.rows:
            click.echo(f"  - {row['pipeline_status']}: {row['cnt']}")
        pipe_client.close()

    asyncio.run(_status())


if __name__ == "__main__":
    main()
