"""utmelab-db: read the bank and production databases without handling a token.

This is a separate command from ``utmelab-bank`` because inspecting data is a
different job from writing the pipeline. It reads ``.env`` through
``load_settings`` and only runs reads, so a token never reaches a command line
and a stray statement can never change either database.

For questions this command does not answer, write a script against the same
library instead of a Turso connection:

    import asyncio
    from utmelab_bank.db import open_database

    async def main() -> None:
        async with open_database("bank") as db:
            result = await db.query(
                "SELECT state, COUNT(*) FROM staging_items GROUP BY state"
            )
            print(result.as_dicts())

    asyncio.run(main())
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from utmelab_bank.adapters.database import DatabaseError
from utmelab_bank.catalog_health import check_catalog
from utmelab_bank.config import ConfigError
from utmelab_bank.db import DATABASES, Database, QueryResult, ReadOnlyError, open_database

#: A hard ceiling on any listing, so a query cannot flood a terminal.
MAX_ROWS = 1000

#: The widest cell a table prints before it is shortened.
MAX_CELL = 120

#: Commands that list staging rows, which only the bank database has.
BANK_ONLY = frozenset({"status", "items", "show", "exams", "subjects"})


def _cell(value: Any) -> str:
    """One value on one line, shortened so the table stays readable."""
    text = "" if value is None else " ".join(str(value).split())
    if len(text) <= MAX_CELL:
        return text
    return f"{text[: MAX_CELL - 3]}..."


def format_table(result: QueryResult) -> str:
    """A plain table: header, rule, rows."""
    if not result.rows:
        return "(no rows)"
    columns = result.columns or tuple(f"column_{index + 1}" for index in range(len(result.rows[0])))
    widths = [len(name) for name in columns]
    for row in result.rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(_cell(value)))
    header = " | ".join(name.ljust(width) for name, width in zip(columns, widths, strict=False))
    rule = "-+-".join("-" * width for width in widths)
    body = [
        " | ".join(_cell(value).ljust(width) for value, width in zip(row, widths, strict=False))
        for row in result.rows
    ]
    return "\n".join([header, rule, *body])


def _print(result: QueryResult, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result.as_dicts(), indent=2, default=str))
        return
    print(format_table(result))


def _pretty(value: Any) -> str:
    """Expand a JSON column so a row is readable, leave anything else alone."""
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.dumps(json.loads(value), indent=2)
        except ValueError:
            return value
    return "" if value is None else str(value)


def _limit(value: int) -> int:
    if value < 1 or value > MAX_ROWS:
        raise ConfigError(f"--limit must be between 1 and {MAX_ROWS}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """The command surface. No database is opened here."""
    parser = argparse.ArgumentParser(
        prog="utmelab-db",
        description="Inspect the bank and production databases. Reads only.",
        epilog=(
            "For a query this command does not answer, import utmelab_bank.db "
            "in a script. The token stays in .env either way."
        ),
    )
    parser.add_argument(
        "--database",
        choices=DATABASES,
        default="bank",
        help="which database to read (default: bank)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print rows as JSON objects",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="state counts and the exam/subject breakdown")

    items = sub.add_parser("items", help="list staging rows")
    items.add_argument("--exam", default=None)
    items.add_argument("--subject", default=None)
    items.add_argument("--year", type=int, default=None)
    items.add_argument("--state", default=None)
    items.add_argument(
        "--limit",
        type=int,
        default=50,
        help=f"at most this many rows (default: 50, max: {MAX_ROWS})",
    )

    show = sub.add_parser("show", help="print one staging row in full")
    show.add_argument("id")

    sub.add_parser("exams", help="list the exams the bank holds")

    subjects = sub.add_parser("subjects", help="list the subjects of one exam")
    subjects.add_argument("exam")

    query = sub.add_parser("query", help="run one read-only SQL statement")
    query.add_argument("sql")

    catalog = sub.add_parser(
        "catalog",
        help="check the production catalog for defects (use --database prod)",
    )
    catalog.add_argument(
        "--strict",
        action="store_true",
        help="also fail on coverage gaps, not just defects",
    )

    return parser


async def _status(db: Database, *, json_output: bool) -> int:
    states = await db.query(
        "SELECT state, COUNT(*) AS rows FROM staging_items GROUP BY state ORDER BY rows DESC"
    )
    scopes = await db.query(
        "SELECT exam, subject, state, COUNT(*) AS rows "
        "FROM staging_items GROUP BY exam, subject, state "
        "ORDER BY exam, subject, state"
    )
    if json_output:
        print(
            json.dumps(
                {
                    "database": db.name,
                    "states": states.as_dicts(),
                    "scopes": scopes.as_dicts(),
                },
                indent=2,
                default=str,
            )
        )
        return 0
    print(f"{db.name} database")
    print("by state:")
    print(format_table(states))
    print()
    print("by exam/subject/state:")
    print(format_table(scopes))
    return 0


async def _items(db: Database, args: argparse.Namespace) -> int:
    where: list[str] = []
    params: list[Any] = []
    if args.exam:
        where.append("exam = ?")
        params.append(args.exam)
    if args.subject:
        where.append("subject = ?")
        params.append(args.subject)
    if args.year is not None:
        where.append("year = ?")
        params.append(args.year)
    if args.state:
        where.append("state = ?")
        params.append(args.state)
    query = (
        "SELECT id, state, exam, subject, year, country, attempts, error, updated_at "
        "FROM staging_items"
    )
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(_limit(args.limit))
    _print(await db.query(query, params), json_output=args.json)
    return 0


async def _show(db: Database, item_id: str, *, json_output: bool) -> int:
    result = await db.query("SELECT * FROM staging_items WHERE id = ?", [item_id])
    if not result.rows:
        print(f"no staging row with id {item_id}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps(result.as_dicts()[0], indent=2, default=str))
        return 0
    for name, value in zip(result.columns, result.rows[0], strict=False):
        print(f"{name}: {_pretty(value)}")
    return 0


async def _catalog(db: Database, *, json_output: bool, strict: bool) -> int:
    health = await check_catalog(db)
    if json_output:
        print(json.dumps(health.as_dict(), indent=2))
        return 0 if health.ok(strict=strict) else 1

    print("production catalog")
    print(
        format_table(
            QueryResult(
                columns=("exam", "subjects", "topics", "subtopics"),
                rows=tuple(
                    (exam.exam, exam.subjects, exam.topics, exam.subtopics) for exam in health.exams
                ),
            )
        )
    )
    print()
    print(f"errors: {health.errors}")
    for item in health.blank_topics:
        print(f"  blank topic name: {item.exam}/{item.subject} {item.slug}")
    for item in health.blank_subtopics:
        print(f"  blank subtopic name: {item.exam}/{item.subject} {item.slug}")
    for item in health.orphan_subtopics:
        print(f"  orphan subtopic: {item.slug} (missing topic {item.subject})")
    print(f"warnings: {health.warnings}")
    for item in health.subjects_without_topics:
        print(f"  subject without topics: {item.exam}/{item.subject}")
    for gap in health.topics_without_subtopics:
        print(f"  topics without subtopics: {gap.exam}/{gap.subject}: {gap.topics}")
    return 0 if health.ok(strict=strict) else 1


async def _execute(args: argparse.Namespace) -> int:
    if args.command == "catalog":
        if args.database != "prod":
            raise ConfigError("the catalog lives in production; use --database prod catalog")
        async with open_database("prod") as db:
            return await _catalog(db, json_output=args.json, strict=args.strict)
    if args.command in BANK_ONLY and args.database != "bank":
        raise ConfigError(f"{args.command} lists staging rows, which only the bank has")
    async with open_database(args.database) as db:
        if args.command == "status":
            return await _status(db, json_output=args.json)
        if args.command == "items":
            return await _items(db, args)
        if args.command == "show":
            return await _show(db, args.id, json_output=args.json)
        if args.command == "exams":
            _print(
                await db.query("SELECT DISTINCT exam FROM staging_items ORDER BY exam"),
                json_output=args.json,
            )
            return 0
        if args.command == "subjects":
            _print(
                await db.query(
                    "SELECT DISTINCT subject FROM staging_items WHERE exam = ? ORDER BY subject",
                    [args.exam],
                ),
                json_output=args.json,
            )
            return 0
        if args.command == "query":
            _print(await db.query(args.sql), json_output=args.json)
            return 0
    raise ConfigError(f"unknown command {args.command!r}")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse, run, report. The only place that turns a result into an exit code."""
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_execute(args))
    except (ReadOnlyError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except DatabaseError as exc:
        print(f"database: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MAX_ROWS", "build_parser", "format_table", "main"]
