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
from utmelab_bank.adapters.providers.opencode import OpenCodeError
from utmelab_bank.config import ConfigError, load_settings
from utmelab_bank.runtime import open_pipeline_runtime, open_store_runtime
from utmelab_bank.tasks import (
    PRESETS,
    TASK_HELP,
    TASKS,
    TaskOptions,
    TaskResult,
    UsageError,
    run_named,
    run_preset,
    summary,
)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
PROVIDERS = ("mock", "opencode")


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
        "--provider",
        choices=PROVIDERS,
        default="opencode",
        help="model provider for the step (default: opencode)",
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
    parser.add_argument(
        "--provider",
        choices=PROVIDERS,
        default="opencode",
        help="model provider (used by the scrape preset's tag step)",
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
        help_text = TASK_HELP.get(name, "Scrape one scope, then tag it.")
        command = sub.add_parser(name, help=help_text)
        _add_fetch(command)

    for name in ("tag", "media", "explain", "review", "ready", "process"):
        command = sub.add_parser(name, help=TASK_HELP.get(name, ""))
        _add_batch(command)

    index_command = sub.add_parser("index", help=TASK_HELP["index"])
    _add_batch(index_command)

    status_command = sub.add_parser("status", help=TASK_HELP["status"])
    _add_batch(status_command)

    return parser


async def _execute(args: argparse.Namespace) -> list[TaskResult]:
    """Open the smallest runtime each command can run with."""
    settings = load_settings()
    options = TaskOptions(
        exam=getattr(args, "exam", None),
        subject=getattr(args, "subject", None),
        year=getattr(args, "year", None),
        section=getattr(args, "section", None),
        limit=getattr(args, "limit", None),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    command = str(args.command)
    provider = getattr(args, "provider", None)

    if command in ("status", "index", "ready"):
        async with open_store_runtime(settings) as runtime:
            return [await run_named(command, runtime, options)]

    if command == "fetch":
        async with open_pipeline_runtime(
            settings,
            source_name=args.source,
            fixture_dir=args.fixture_dir,
            media=True,
        ) as runtime:
            return [await run_named("fetch", runtime, options)]

    if command == "scrape":
        async with open_pipeline_runtime(
            settings,
            source_name=args.source,
            fixture_dir=args.fixture_dir,
            provider_name=provider,
            media=True,
            text=True,
        ) as runtime:
            return await run_preset("scrape", runtime, options)

    if command == "tag":
        async with open_pipeline_runtime(settings, provider_name=provider, text=True) as runtime:
            return [await run_named("tag", runtime, options)]

    if command == "media":
        async with open_pipeline_runtime(
            settings, provider_name=provider, media=True, image=True
        ) as runtime:
            return [await run_named("media", runtime, options)]

    if command == "explain":
        async with open_pipeline_runtime(settings, provider_name=provider, text=True) as runtime:
            return [await run_named("explain", runtime, options)]

    if command == "review":
        async with open_pipeline_runtime(settings, provider_name=provider, text=True) as runtime:
            return [await run_named("review", runtime, options)]

    if command == "process":
        async with open_pipeline_runtime(
            settings,
            provider_name=provider,
            media=True,
            text=True,
            image=True,
        ) as runtime:
            return await run_preset("process", runtime, options)

    raise UsageError(f"unknown command {command!r}")


def _print_tasks(*, json_output: bool) -> None:
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


def _print_results(results: Sequence[TaskResult], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps([result.as_dict() for result in results], indent=2))
        return
    for result in results:
        print(f"{result.task}: {summary(result)}")
        for note in result.notes:
            print(f"  {note}")
        for error in result.errors:
            print(f"  ERROR: {error}")


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

    try:
        results = asyncio.run(_execute(args))
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    except (DatabaseError, MediaError, OpenCodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        logging.getLogger(__name__).exception("the run failed")
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _print_results(results, json_output=args.json)
    return 0 if all(result.ok for result in results) else 1


__all__ = ["build_parser", "main"]
