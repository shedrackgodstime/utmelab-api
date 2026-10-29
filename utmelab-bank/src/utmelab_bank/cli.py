"""The command line. One binary, one task per command, two presets.

The CLI is thin on purpose. It parses the inputs, opens only the parts the
command needs, calls the task runner, and prints the result. Every decision
about content lives in the services; every decision about what is legal lives
in the state machine. A command that cannot run says why and exits 2, a run
with a failed or blocked row exits 1, and a clean run exits 0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from utmelab_bank.adapters.database import DatabaseError
from utmelab_bank.adapters.media import MediaError
from utmelab_bank.adapters.providers import OpenAICompatibleError, ProviderExhausted
from utmelab_bank.adapters.providers.opencode import OpenCodeError
from utmelab_bank.adapters.sources import create_source
from utmelab_bank.config import ConfigError, load_settings, catalog_write_credentials
from utmelab_bank.runtime import Runtime, open_pipeline_runtime, open_store_runtime
from utmelab_bank.tasks import (
    PRESETS,
    TASK_HELP,
    TASKS,
    TaskOptions,
    TaskResult,
    UsageError,
    probe,
    run_named,
    run_preset,
    summary,
)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
PROVIDERS = ("opencode", "openai", "config")


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the task results as JSON",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=LOG_LEVELS,
        default="INFO",
        help="how much of the run to log (default: INFO)",
    )


def _add_scope(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument("--exam", required=required, help="exam, e.g. JAMB")
    parser.add_argument(
        "--subject",
        required=required,
        help="subject slug, e.g. biology (production uses the slug, not the name)",
    )
    parser.add_argument("--year", type=int, required=required, help="exam year")
    parser.add_argument("--section", default=None, help="optional paper section")
    parser.add_argument("--country", default=None, help="country code, e.g. NG")


def _add_batch(parser: argparse.ArgumentParser) -> None:
    _add_scope(parser, required=False)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="at most this many rows (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the work without writing anything",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=3,
        help="stop the task after this many consecutive failures (0 means no cap)",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        default="config",
        help="model provider for the step (default: config)",
    )
    _add_output(parser)


def _add_fetch(parser: argparse.ArgumentParser) -> None:
    _add_scope(parser, required=True)
    parser.add_argument(
        "--source",
        default="fixture",
        help="source adapter to scrape (default: fixture)",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="fixture directory for the fixture source",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="at most this many source items (no default for a scrape)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="probe the scope without writing anything",
    )
    _add_output(parser)


def build_parser() -> argparse.ArgumentParser:
    """The full command surface, with no model or database call in it."""
    parser = argparse.ArgumentParser(
        prog="utmelab-bank",
        description="Ingest, gate, review and hand over exam content.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    tasks = sub.add_parser("tasks", help="list the tasks and presets")
    _add_output(tasks)

    for name in ("fetch", "scrape"):
        help_text = TASK_HELP.get(name, "Scrape one scope, gate it, and stop at deduped.")
        command = sub.add_parser(name, help=help_text)
        _add_fetch(command)

    for name in ("capture", "tag", "media", "explain", "review", "ready", "process"):
        command = sub.add_parser(name, help=TASK_HELP.get(name, ""))
        _add_batch(command)

    index_command = sub.add_parser("index", help=TASK_HELP["index"])
    _add_batch(index_command)

    status_command = sub.add_parser("status", help=TASK_HELP["status"])
    _add_batch(status_command)

    migrate = sub.add_parser("migrate", help="Apply catalog migrations to production (WAEC subject alignment)")
    migrate.add_argument("--apply", action="store_true", help="Execute the migration (default: dry-run)")
    migrate.add_argument("--yes", action="store_true", help="Skip confirmation prompt when applying")
    _add_output(migrate)

    bank_clear = sub.add_parser("bank-clear", help="Clear WAEC data from bank database (one-time cleanup)")
    bank_clear.add_argument("--apply", action="store_true", help="Execute the cleanup (default: dry-run)")
    bank_clear.add_argument("--yes", action="store_true", help="Skip confirmation prompt when applying")
    _add_output(bank_clear)

    return parser


async def _execute(args: argparse.Namespace) -> tuple[list[TaskResult], str | None, str | None]:
    """Open the smallest runtime each command can run with. Returns (results, provider, model)."""
    options = TaskOptions(
        exam=getattr(args, "exam", None),
        subject=getattr(args, "subject", None),
        year=getattr(args, "year", None),
        section=getattr(args, "section", None),
        country=getattr(args, "country", None),
        limit=getattr(args, "limit", None),
        max_failures=getattr(args, "max_failures", 3),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    command = str(args.command)
    provider = getattr(args, "provider", None)
    actual_provider: str | None = None
    actual_model: str | None = None

    def _get_provider_info(runtime: Runtime) -> tuple[str | None, str | None]:
        """Extract provider name and model from runtime's providers."""
        # Text provider
        if runtime.tagger and hasattr(runtime.tagger, "producer"):
            prod = runtime.tagger.producer
            return prod.provider, prod.model
        if runtime.explainer and hasattr(runtime.explainer, "producer"):
            prod = runtime.explainer.producer
            return prod.provider, prod.model
        if runtime.verifier and hasattr(runtime.verifier, "producer"):
            prod = runtime.verifier.producer
            return prod.provider, prod.model
        # Image provider (describer has two witnesses)
        if runtime.media and getattr(runtime.media, "_describer", None):
            describer = runtime.media._describer
            witnesses = getattr(describer, "witnesses", None)
            if witnesses:
                prod = witnesses[0].producer
                return f"consensus({prod.provider})", prod.model
        return None, None

    if command in ("fetch", "scrape") and options.dry_run:
        source = create_source(args.source, fixture_dir=args.fixture_dir)
        try:
            return [await probe(source, options)], None, None
        finally:
            close = getattr(source, "close", None)
            if callable(close):
                await close()

    settings = load_settings()

    if command in ("status", "index", "ready"):
        async with open_store_runtime(settings) as runtime:
            return [await run_named(command, runtime, options)], None, None

    if command == "fetch":
        async with open_pipeline_runtime(
            settings,
            source_name=args.source,
            fixture_dir=args.fixture_dir,
            media=True,
        ) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return [await run_named("fetch", runtime, options)], actual_provider, actual_model

    if command == "scrape":
        async with open_pipeline_runtime(
            settings,
            source_name=args.source,
            fixture_dir=args.fixture_dir,
            media=True,
        ) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return await run_preset("scrape", runtime, options), actual_provider, actual_model

    if command == "capture":
        async with open_pipeline_runtime(settings, media=True) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return [await run_named("capture", runtime, options)], actual_provider, actual_model

    if command == "tag":
        async with open_pipeline_runtime(
            settings, provider_name=provider, routing_task="topic_classification", text=True
        ) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return [await run_named("tag", runtime, options)], actual_provider, actual_model

    if command == "media":
        async with open_pipeline_runtime(
            settings, provider_name=provider, media=True, image=True
        ) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return [await run_named("media", runtime, options)], actual_provider, actual_model

    if command == "explain":
        async with open_pipeline_runtime(settings, provider_name=provider, text=True) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return [await run_named("explain", runtime, options)], actual_provider, actual_model

    if command == "review":
        async with open_pipeline_runtime(settings, provider_name=provider, text=True) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return [await run_named("review", runtime, options)], actual_provider, actual_model

    if command == "process":
        async with open_pipeline_runtime(
            settings,
            provider_name=provider,
            media=True,
            text=True,
            image=True,
        ) as runtime:
            actual_provider, actual_model = _get_provider_info(runtime)
            return await run_preset("process", runtime, options), actual_provider, actual_model

    if command == "migrate":
        return await _execute_migrate(args), None, None

    if command == "bank-clear":
        return await _execute_bank_clear(args), None, None

    raise UsageError(f"unknown command {command!r}")


async def _execute_migrate(args: argparse.Namespace) -> list:
    """Execute the WAEC subject catalog migration."""
    from utmelab_bank.adapters.database import TursoClient
    from utmelab_bank.config import catalog_write_credentials

    # Migration plan
    updates = [
        # (old_slug, new_slug, new_name)
        ("agricultural-science", "agriculture", "Agriculture"),
        ("animal-husbandry", "livestock-farming", "Livestock Farming"),
        ("financial-accounting", "accounting", "Accounting"),
        ("visual-arts", "visual-art", "Visual Art"),
    ]
    name_only_updates = [
        ("health-education", "Health Education / Health Science"),
        ("literature-in-english", "Literature-In-English"),
    ]
    inserts = [
        ("arabic", "Arabic", ["NG"]),
        ("beauty-and-cosmetology", "Beauty & Cosmetology", ["NG"]),
        ("computer-hardware-and-gsm-repairs", "Computer Hardware and GSM Repairs", ["NG"]),
        ("fashion-design-and-garment-making", "Fashion Design & Garment Making", ["NG"]),
        ("solar-photovoltaic-installation-and-maintenance", "Solar Photovoltaic Installation and Maintenance", ["NG"]),
        ("citizenship-and-heritage-studies", "Citizenship and Heritage Studies Education", ["NG"]),
        ("digital-technologies", "Digital Technologies", ["NG"]),
        ("horticulture-and-crop-production", "Horticulture and Crop Production", ["NG"]),
    ]

    dry_run = not args.apply
    json_out = args.json

    # Print plan
    if json_out:
        plan = {
            "dry_run": dry_run,
            "updates": [{"old_slug": u[0], "new_slug": u[1], "new_name": u[2]} for u in updates],
            "name_only_updates": [{"slug": u[0], "new_name": u[1]} for u in name_only_updates],
            "inserts": [{"slug": u[0], "name": u[1], "countries": u[2]} for u in inserts],
        }
        print(json.dumps(plan, indent=2))
    else:
        print("=== WAEC Subject Catalog Migration ===")
        print(f"Mode: {'DRY-RUN' if dry_run else 'APPLY'}")
        print()
        print("Slug + name changes:")
        for old, new, name in updates:
            print(f"  {old} -> {new}  (name: {name})")
        print()
        print("Name-only updates:")
        for slug, name in name_only_updates:
            print(f"  {slug} -> {name}")
        print()
        print("New subjects to insert:")
        for slug, name, countries in inserts:
            print(f"  {slug} | {name} | countries={countries}")
        print()

    if dry_run:
        print("DRY-RUN: no changes made. Re-run with --apply to execute.")
        return []

    # Confirm
    if not args.yes:
        try:
            confirm = input("Apply these changes to PRODUCTION catalog? [y/N]: ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y":
            print("Aborted.")
            return []

    # Get write credentials and execute
    prod_url, prod_token = catalog_write_credentials()
    client = TursoClient(prod_url, prod_token, retries=3, backoff=1.5)

    try:
        # Start transaction by running statements with commit=False, then commit at end
        await client.execute("BEGIN", commit=False)

        # 1. Update slugs + names (need to update all FK references first)
        for old_slug, new_slug, new_name in updates:
            # Update topics (FK to subjects.slug)
            await client.execute(
                "UPDATE topics SET subject = ? WHERE subject = ? AND exam = 'WAEC'",
                [new_slug, old_slug],
                commit=False,
            )
            # Update questions (subject column)
            await client.execute(
                "UPDATE questions SET subject = ? WHERE subject = ? AND exam = 'WAEC'",
                [new_slug, old_slug],
                commit=False,
            )
            # Update passages (subject column)
            await client.execute(
                "UPDATE passages SET subject = ? WHERE subject = ? AND exam = 'WAEC'",
                [new_slug, old_slug],
                commit=False,
            )
            # Update exam_requirements.subjects JSON array
            await client.execute(
                "UPDATE exam_requirements SET subjects = json_set(subjects, '$', (SELECT json_group_array(CASE WHEN value = ? THEN ? ELSE value END) FROM json_each(subjects))) WHERE exam = 'WAEC' AND json_type(subjects) = 'array'",
                [old_slug, new_slug],
                commit=False,
            )
            # Update blueprints (subject column)
            await client.execute(
                "UPDATE blueprints SET subject = ? WHERE subject = ? AND exam = 'WAEC'",
                [new_slug, old_slug],
                commit=False,
            )
            # Update subjects
            await client.execute(
                "UPDATE subjects SET slug = ?, name = ?, syllabus_subject = ? WHERE slug = ? AND exam = 'WAEC'",
                [new_slug, new_name, new_slug, old_slug],
                commit=False,
            )

        # 2. Name-only updates
        for slug, new_name in name_only_updates:
            await client.execute(
                "UPDATE subjects SET name = ? WHERE slug = ? AND exam = 'WAEC'",
                [new_name, slug],
                commit=False,
            )

        # 3. Insert new subjects
        for slug, name, countries in inserts:
            countries_json = json.dumps(countries)
            await client.execute(
                """INSERT INTO subjects (slug, exam, name, is_compulsory, objective_paper_questions,
                   syllabus_exam, syllabus_subject, countries)
                   VALUES (?, 'WAEC', ?, 0, 50, 'WAEC', ?, ?)""",
                [slug, name, slug, countries_json],
                commit=False,
            )

        # Commit transaction
        await client.commit()

        print("Migration applied successfully.")
        if not json_out:
            print("Verifying...")
        # Quick verification
        for old_slug, new_slug, _ in updates:
            result = await client.execute(
                "SELECT slug, name FROM subjects WHERE slug = ? AND exam = 'WAEC'", [new_slug]
            )
            if result.rows:
                print(f"  subjects: {result.rows[0][0]} | {result.rows[0][1]}")
            # Verify topics
            result = await client.execute(
                "SELECT COUNT(*) FROM topics WHERE subject = ? AND exam = 'WAEC'", [new_slug]
            )
            print(f"  topics with {new_slug}: {result.rows[0][0]}")
            # Verify questions
            result = await client.execute(
                "SELECT COUNT(*) FROM questions WHERE subject = ? AND exam = 'WAEC'", [new_slug]
            )
            print(f"  questions with {new_slug}: {result.rows[0][0]}")
            # Verify passages
            result = await client.execute(
                "SELECT COUNT(*) FROM passages WHERE subject = ? AND exam = 'WAEC'", [new_slug]
            )
            print(f"  passages with {new_slug}: {result.rows[0][0]}")
            # Verify blueprints
            result = await client.execute(
                "SELECT COUNT(*) FROM blueprints WHERE subject = ? AND exam = 'WAEC'", [new_slug]
            )
            print(f"  blueprints with {new_slug}: {result.rows[0][0]}")
        for slug, name, _ in inserts:
            result = await client.execute(
                "SELECT slug, name FROM subjects WHERE slug = ? AND exam = 'WAEC'", [slug]
            )
            if result.rows:
                print(f"  Verified: {result.rows[0][0]} | {result.rows[0][1]}")

        return [{"status": "applied", "updates": len(updates), "inserts": len(inserts)}]

    except Exception as exc:
        # Rollback on error
        try:
            await client.execute("ROLLBACK", commit=False)
        except Exception:
            pass
        raise
    finally:
        await client.close()


async def _execute_bank_clear(args: argparse.Namespace) -> list:
    """Clear WAEC data from bank database (one-time cleanup)."""
    from utmelab_bank.adapters.database import TursoClient
    from utmelab_bank.config import bank_write_credentials

    dry_run = not args.apply
    json_out = args.json

    if json_out:
        plan = {"dry_run": dry_run, "action": "DELETE FROM staging_items WHERE exam='WAEC'; DELETE FROM passages WHERE exam='WAEC'"}
        print(json.dumps(plan, indent=2))
    else:
        print("=== Bank WAEC Data Cleanup ===")
        print(f"Mode: {'DRY-RUN' if dry_run else 'APPLY'}")
        print("Will delete from bank database:")
        print("  DELETE FROM staging_items WHERE exam='WAEC';")
        print("  DELETE FROM passages WHERE exam='WAEC';")
        print()

    if dry_run:
        print("DRY-RUN: no changes made. Re-run with --apply to execute.")
        return []

    if not args.yes:
        try:
            confirm = input("Delete ALL WAEC data from bank database? [y/N]: ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y":
            print("Aborted.")
            return []

    bank_url, bank_token = bank_write_credentials()
    client = TursoClient(bank_url, bank_token, retries=3, backoff=1.5)

    try:
        await client.execute("BEGIN", commit=False)
        await client.execute("DELETE FROM staging_items WHERE exam='WAEC'", commit=False)
        await client.execute("DELETE FROM passages WHERE exam='WAEC'", commit=False)
        await client.commit()
        print("Bank WAEC data cleared successfully.")
        return [{"status": "cleared", "tables": ["staging_items", "passages"]}]
    except Exception as exc:
        try:
            await client.execute("ROLLBACK", commit=False)
        except Exception:
            pass
        raise
    finally:
        await client.close()
    if json_output:
        print(
            json.dumps(
                {
                    "tasks": list(TASKS),
                    "presets": {name: list(steps) for name, steps in PRESETS.items()},
                },
                indent=2,
            )
        )
        return
    print("tasks:")
    for name, description in TASK_HELP.items():
        print(f"  {name:10} {description}")
    print("presets:")
    for name, steps in PRESETS.items():
        print(f"  {name:10} {' -> '.join(steps)}")


def _print_results(
    results: Sequence[TaskResult],
    *,
    json_output: bool,
    provider: str | None = None,
    model: str | None = None,
    duration: float | None = None,
) -> None:
    if json_output:
        print(json.dumps([result.as_dict() for result in results], indent=2))
        return
    for result in results:
        print(f"{result.task}: {summary(result)}")
        for note in result.notes:
            print(f"  {note}")
        for error in result.errors:
            print(f"  ERROR: {error}")
        if result.stopped:
            print("  STOPPED: the batch hit its consecutive-failure limit")

    if not json_output and results:
        total_seen = sum(r.seen for r in results)
        total_done = sum(r.done for r in results)
        total_skipped = sum(r.skipped for r in results)
        total_failed = sum(r.failed for r in results)
        total_blocked = sum(r.blocked for r in results)
        print()
        print("=" * 60)
        print("RUN SUMMARY")
        print("=" * 60)
        print(f"Command:        {results[0].task if len(results) == 1 else 'preset'}")
        if provider:
            print(f"Provider:       {provider}")
        if model:
            print(f"Model:          {model}")
        if duration is not None:
            print(f"Duration:       {duration:.1f}s")
        print(f"Total seen:     {total_seen}")
        print(f"  Done:         {total_done}")
        print(f"  Skipped:      {total_skipped}")
        print(f"  Failed:       {total_failed}")
        print(f"  Blocked:      {total_blocked}")
        print(f"All OK:         {'yes' if all(r.ok for r in results) else 'no'}")
        print("=" * 60)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, run, print. The only place that turns a result into an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "tasks":
        _print_tasks(json_output=args.json)
        return 0

    import time

    start_time = time.perf_counter()
    try:
        results, actual_provider, actual_model = asyncio.run(_execute(args))
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    except (
        DatabaseError,
        MediaError,
        ProviderExhausted,
        OpenCodeError,
        OpenAICompatibleError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        logging.getLogger(__name__).exception("the run failed")
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    duration = time.perf_counter() - start_time
    _print_results(
        results,
        json_output=args.json,
        provider=actual_provider,
        model=actual_model,
        duration=duration,
    )
    return 0 if all(result.ok for result in results) else 1


__all__ = ["build_parser", "main"]
