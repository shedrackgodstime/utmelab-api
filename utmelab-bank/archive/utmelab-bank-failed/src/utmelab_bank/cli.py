"""One entry point, over both registries.

The point of a single CLI is that a step you can run in a terminal you can run
in a workflow, with the same name and the same flags. The previous Python had
six workflows because the code was in two places, and each workflow carried
logic the other did not.

Two groups of commands:

- ``scrape`` and ``fill`` use a *source*.
- everything else uses a *task*.

Both take ``--where``, ``--sink`` and ``--target``, so a run reads the same way
whichever half it belongs to.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, TypeVar, cast

import click

from utmelab_bank import __version__
from utmelab_bank.config import Config, load
from utmelab_bank.errors import BankError, ConfigError, ContractError, SourceError, TaskError
from utmelab_bank.source.raw import (
    raw_passage_row as _raw_passage_row,
    raw_row as _raw_row,
)
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository

F = TypeVar("F", bound=Callable[..., Any])

log = logging.getLogger("utmelab_bank")


def _setup_logging(level: str) -> None:
    """One text sink. ``LOG_FORMAT=json`` is a deployment concern, so it lives
    in the environment rather than in a flag."""
    import os

    handler = logging.StreamHandler(sys.stderr)
    if os.environ.get("LOG_FORMAT") == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


class _JsonFormatter(logging.Formatter):
    """One json object per line, with the record flattened."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "target": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in {"message", "asctime", "exc_info"} and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str)


def _config(**overrides: Any) -> Config:
    flags: dict[str, str] = {}
    for name, value in overrides.items():
        if value not in (None, False):
            flags[name] = str(value)
    return load(where=flags, **overrides)


def reports_errors(command: Any) -> Any:
    """Turn a refusal into a line a person can act on.

    Without this a ``ContractError`` or ``SourceError`` reaches the user as a
    traceback, and a refusal that looks like a crash is one nobody reads.
    """

    @functools.wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except BankError as exc:
            click.echo(f"{exc.code}: {exc}", err=True)
            raise SystemExit(exc_code_for(exc)) from None
        except SystemExit:
            raise
        except click.ClickException:
            raise
        except KeyboardInterrupt:
            click.echo("interrupted", err=True)
            raise SystemExit(130) from None

    return wrapper


def exc_code_for(error: BankError) -> int:
    """Exit codes a workflow can act on: 0 fine, 1 something failed, 2 refused."""
    if isinstance(error, ContractError | ConfigError | SourceError | TaskError):
        return 2
    return 1


_common = [
    click.option("--target", default="work", help="raw, work or ready. ready is our 'prod' lane."),
    click.option(
        "--sink", type=click.Choice(["db", "json"]), default=None, help="Where rows land."
    ),
    click.option(
        "--local-database",
        type=click.Path(path_type=Path),
        default=None,
        help="A local sqlite file. Accepts a bare path, file: or sqlite:.",
    ),
    click.option("--log-level", default=None),
]


def _add_common(command: F) -> F:
    for option in reversed(_common):
        command = option(command)
    return command


def _command(name: str) -> Callable[[F], F]:
    """``cli.command``, with error reporting already attached."""

    def wrap(function: F) -> F:
        return cast(F, cli.command(name)(reports_errors(function)))

    return wrap


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="utmelab-bank")
@click.option("--log-level", default=None, help="debug, info, warning, error.")
def cli(log_level: str | None) -> None:
    """Acquire, judge and mark questions ready for production."""
    _setup_logging(log_level or "info")


@_command("scrape")
@click.option("--source", required=True, help="Where to fetch from. See ``sources``.")
@click.option("--exam", required=True, help="jamb, waec or neco.")
@click.option("--subject", required=True)
@click.option("--year", type=int, default=None)
@click.option("--limit", type=int, default=None, help="Stop after this many questions.")
@click.option("--pages", type=int, default=None, help="Stop after this many listing pages.")
@click.option("--delay", type=float, default=None, help="Seconds between requests.")
@click.option("--dry-run", is_flag=True, help="Fetch and count. Write nothing.")
@click.option("--strategy", default=None, help="api or html, where a source offers both.")
@_add_common
def scrape_cmd(
    source: str,
    exam: str,
    subject: str,
    year: int | None,
    limit: int | None,
    pages: int | None,
    delay: float | None,
    dry_run: bool,
    strategy: str | None,
    target: str,
    sink: str | None,
    local_database: Path | None,
    log_level: str | None,
) -> None:
    """Fetch questions into the raw lane. Writes nothing else."""
    raise SystemExit(
        asyncio.run(
            _scrape(
                source=source,
                exam=exam,
                subject=subject,
                year=year,
                limit=limit,
                pages=pages,
                delay=delay,
                dry_run=dry_run,
                strategy=strategy,
                target=target,
                sink=sink,
                local_database=local_database,
                log_level=log_level,
            )
        )
    )


async def _scrape(**kwargs: Any) -> int:
    from utmelab_bank.model.base import now_iso
    from utmelab_bank.source import FetchRequest, build_source
    from utmelab_bank.source.myschool.run import fetch_subject
    from utmelab_bank.store.repository import Repository
    from utmelab_bank.store.schema import ensure_schema

    config = _config(
        target=kwargs["target"],
        sink=kwargs["sink"],
        local_database=kwargs["local_database"],
    )
    _setup_logging(kwargs["log_level"] or config.log_level)
    run_id = f"r_scrape_{now_iso().replace(':', '').replace('-', '')}"

    request = FetchRequest(
        exam=kwargs["exam"],
        subject=kwargs["subject"],
        year=kwargs["year"],
        limit=kwargs["limit"],
        pages=kwargs["pages"],
        delay=kwargs["delay"],
    )
    plugin = build_source(request_source := kwargs["source"], strategy=kwargs.get("strategy"))
    if not plugin.supports(request):
        click.echo(
            f"{request_source} does not serve {request.exam}; it serves "
            f"{', '.join(plugin.capabilities().exams)}",
            err=True,
        )
        return 2

    if kwargs["dry_run"]:
        count = await plugin.probe(request, config)  # type: ignore[attr-defined]
        click.echo(f"{count} questions available for {request.exam} {request.subject}")
        return 0

    async with _open(config) as store:
        await ensure_schema(store)
        repo = Repository(store, lane="raw")
        parsed = await fetch_subject(request, config, strategy=kwargs.get("strategy") or "api")

        figures = sum(len(item.figures) for item in parsed)
        if figures:
            click.echo(f"  {figures} figures referenced")

        rows = [_raw_row(item, run_id) for item in parsed]
        passages = [row for item in parsed if (row := _raw_passage_row(item)) is not None]
        if passages:
            await repo.insert_many("passages", passages)
        written = await repo.insert_many("questions", rows)

        already = len(rows) - written
        click.echo(f"fetched {len(parsed)}, wrote {written} to raw_questions")
        if already:
            click.echo(f"  {already} were already there, nothing changed")
        if not parsed:
            click.echo(
                "nothing was fetched. The api serves five rows a page, so check "
                "the subject slug and the year before assuming the paper is short.",
                err=True,
            )
            return 1
        return 0


@_command("fill")
@click.option("--source", default="myschool", help="Where to fetch from. myschool for now.")
@click.option("--exam", default="jamb", help="jamb, waec or neco.")
@click.option(
    "--subject",
    multiple=True,
    help="A subject slug from the source map. Repeatable. Default: all.",
)
@click.option("--from-year", type=int, default=None, help="Oldest year in the window.")
@click.option("--to-year", type=int, default=None, help="Newest year in the window.")
@click.option("--minutes", type=float, default=50.0, help="Stop after this many minutes.")
@click.option("--max-targets", type=int, default=None, help="Stop after this many targets.")
@click.option("--delay", type=float, default=None, help="Seconds between requests.")
@click.option("--strategy", default="api", help="api or html, where a source offers both.")
@click.option("--refresh", is_flag=True, help="Re-queue drained and empty targets.")
@click.option("--dry-run", is_flag=True, help="Print the plan. Write nothing.")
@_add_common
def fill_cmd(
    source: str,
    exam: str,
    subject: tuple[str, ...],
    from_year: int | None,
    to_year: int | None,
    minutes: float,
    max_targets: int | None,
    delay: float | None,
    strategy: str,
    refresh: bool,
    dry_run: bool,
    target: str,
    sink: str | None,
    local_database: Path | None,
    log_level: str | None,
) -> None:
    """Walk the plan and fetch every target until the source or budget ends.

    The plan is ``(source, exam, subject, year)`` and nothing else. Newest year
    first, subjects in the source map's order. A drained or empty target leaves
    the queue; a failed one backs off and is retried. The plan lives in the
    bank database, so the next run continues where this one stopped.
    """
    raise SystemExit(
        asyncio.run(
            _fill(
                source=source,
                exam=exam,
                subjects=subject,
                from_year=from_year,
                to_year=to_year,
                minutes=minutes,
                max_targets=max_targets,
                delay=delay,
                strategy=strategy,
                refresh=refresh,
                dry_run=dry_run,
                target=target,
                sink=sink,
                local_database=local_database,
                log_level=log_level,
            )
        )
    )


async def _fill(**kwargs: Any) -> int:
    from utmelab_bank.fill import FillOptions, plan, run_fill
    from utmelab_bank.store.schema import ensure_schema

    config = _config(
        target=kwargs["target"],
        sink=kwargs["sink"],
        local_database=kwargs["local_database"],
    )
    _setup_logging(kwargs["log_level"] or config.log_level)
    options = FillOptions(
        source=kwargs["source"],
        exam=kwargs["exam"],
        subjects=tuple(kwargs["subjects"]),
        from_year=kwargs["from_year"],
        to_year=kwargs["to_year"],
        minutes=kwargs["minutes"],
        max_targets=kwargs["max_targets"],
        delay=kwargs["delay"],
        strategy=kwargs["strategy"],
        refresh=kwargs["refresh"],
    )

    if kwargs["dry_run"]:
        rows = plan(options)
        click.echo(f"{len(rows)} targets, newest year first")
        for row in rows[:25]:
            click.echo(f"  {row['exam']} {row['subject']} {row['year']}")
        if len(rows) > 25:
            click.echo(f"  ... {len(rows) - 25} more")
        return 0

    async with _open(config) as store:
        await ensure_schema(store)
        report = await run_fill(config, store, options)
        click.echo(report.summary())
        click.echo(
            f"  drained {report.drained}, empty {report.empty}, "
            f"failed {report.failed}, seeded {report.seeded}, reset {report.reset}"
        )
        if report.reason != "done":
            click.echo(f"  stopped: {report.reason} after {report.elapsed:.0f}s")
        click.echo(f"  database: {report.database}")
        return 0 if report.failed == 0 else 1


@_command("task")
@click.argument("name")
@click.option("--where", default="all", help="A selector expression. See ``selectors``.")
@click.option("--limit", type=int, default=None)
@click.option("--table", default="questions", help="The logical table to iterate.")
@click.option("--dry-run", is_flag=True)
@_add_common
def task_cmd(
    name: str,
    where: str,
    limit: int | None,
    table: str,
    dry_run: bool,
    target: str,
    sink: str | None,
    local_database: Path | None,
    log_level: str | None,
) -> None:
    """Run one task over the rows a selector picks."""
    raise SystemExit(
        asyncio.run(
            _task(
                name=name,
                where=where,
                limit=limit,
                table=table,
                dry_run=dry_run,
                target=target,
                sink=sink,
                local_database=local_database,
                log_level=log_level,
            )
        )
    )


async def _task(**kwargs: Any) -> int:
    from utmelab_bank.store.repository import Repository
    from utmelab_bank.store.schema import ensure_schema
    from utmelab_bank.task import get, run_task

    config = _config(
        target=kwargs["target"],
        sink=kwargs["sink"],
        local_database=kwargs["local_database"],
    )
    _setup_logging(kwargs["log_level"] or config.log_level)

    plugin = get(kwargs["name"])

    async with _open(config) as store:
        await ensure_schema(store)
        repo = Repository(store, lane=config.lane)
        result = await run_task(
            plugin,
            config,
            repo,
            where=kwargs["where"],
            logical=kwargs["table"],
            limit=kwargs["limit"],
            dry_run=kwargs["dry_run"],
            progress=lambda done, _total: click.echo(f"  {done} rows", err=True),
        )

    click.echo(result.summary())
    if result.run.detail:
        click.echo(result.run.detail, err=True)
    return result.exit_code


@cli.command("sources")
def sources_cmd() -> None:
    """What each source can fetch."""
    from utmelab_bank.source import all_sources, get

    for name in all_sources():
        caps = get(name).capabilities()
        click.echo(f"{name}")
        click.echo(f"  exams     {', '.join(caps.exams) or 'none'}")
        click.echo(f"  media     {'yes' if caps.media else 'no'}")
        if caps.note:
            click.echo(f"  note      {caps.note}")


@_command("goal")
@click.argument("name")
@click.option("--task", "tasks", multiple=True, help="Task name; repeatable, run in order given.")
@click.option(
    "--where", default="all", help="Selector expression for every task (task:where overrides)."
)
@click.option("--limit", type=int, default=None)
@click.option("--table", default="questions", help="The logical table to iterate.")
@click.option("--dry-run", is_flag=True)
@_add_common
def goal_cmd(
    name: str,
    tasks: tuple[str, ...],
    where: str,
    limit: int | None,
    table: str,
    dry_run: bool,
    target: str,
    sink: str | None,
    local_database: Path | None,
    log_level: str | None,
) -> None:
    """Run named tasks in sequence as one goal.

    A name that matches a preset (currently ``media``) runs that fixed, ordered
    flow with its own table per step. Otherwise pass one or more ``--task``
    flags. Steps are independent units; the goal just wires them together. No
    task calls another. A failed step stops the goal.
    """
    raise SystemExit(
        asyncio.run(
            _goal(
                name=name,
                tasks=tasks,
                where=where,
                limit=limit,
                table=table,
                dry_run=dry_run,
                target=target,
                sink=sink,
                local_database=local_database,
                log_level=log_level,
            )
        )
    )


async def _goal(**kwargs: Any) -> int:
    from dataclasses import replace

    from utmelab_bank.store.repository import Repository
    from utmelab_bank.store.schema import ensure_schema
    from utmelab_bank.task.goal import PRESETS, Step, run_goal

    config = _config(
        target=kwargs["target"],
        sink=kwargs["sink"],
        local_database=kwargs["local_database"],
    )
    _setup_logging(kwargs["log_level"] or config.log_level)

    steps: list[Step] = []
    if kwargs["tasks"]:
        for task_spec in kwargs["tasks"]:
            task_name, step_where = _parse_task_spec(task_spec, kwargs["where"])
            steps.append(
                Step(
                    task=task_name,
                    where=step_where,
                    limit=kwargs["limit"],
                    logical=kwargs["table"],
                )
            )
    else:
        preset = PRESETS.get(kwargs["name"])
        if preset is None:
            known = ", ".join(sorted(PRESETS))
            raise click.ClickException(
                f"goal needs at least one --task, or a known goal name: {known}"
            )
        steps = [replace(step, limit=kwargs["limit"]) for step in preset.steps]

    async with _open(config) as store:
        await ensure_schema(store)
        repo = Repository(store, lane=config.lane)
        results = await run_goal(
            config, repo, kwargs["name"], tuple(steps), dry_run=kwargs["dry_run"]
        )

    any_failed = False
    any_broken = False
    for result in results:
        click.echo(result.summary())
        if result.run.detail:
            click.echo(result.run.detail, err=True)
        if result.run.failed:
            any_failed = True
        if result.run.status == "broken":
            any_broken = True

    if any_broken:
        return 2
    if any_failed:
        return 1
    return 0


def _parse_task_spec(task_spec: str, default_where: str) -> tuple[str, str]:
    """Split ``task:where`` into (task, where); the colon is optional."""
    if ":" in task_spec:
        task_name, where = task_spec.split(":", 1)
        return task_name, where
    return task_spec, default_where


@_command("status")
@click.option("--json", "as_json", is_flag=True, help="Print the snapshot as json.")
@_add_common
def status_cmd(
    as_json: bool,
    target: str,
    sink: str | None,
    local_database: Path | None,
    log_level: str | None,
) -> None:
    """Show lane counts, queues and recent runs. Reads only."""
    raise SystemExit(
        asyncio.run(
            _status(
                as_json=as_json,
                target=target,
                sink=sink,
                local_database=local_database,
                log_level=log_level,
            )
        )
    )


async def _status(
    *,
    as_json: bool,
    target: str,
    sink: str | None,
    local_database: Path | None,
    log_level: str | None,
) -> int:
    from dataclasses import asdict

    from utmelab_bank.report.status import collect_status, render_status
    from utmelab_bank.store.schema import ensure_schema

    config = _config(target=target, sink=sink, local_database=local_database)
    _setup_logging(log_level or config.log_level)
    if config.sink == "json":
        click.echo("status needs the database; the json sink holds no lanes", err=True)
        return 2

    async with _open(config) as store:
        await ensure_schema(store)
        report = await collect_status(store, config.lane, config.require_database())

    if as_json:
        click.echo(json.dumps(asdict(report), indent=2, sort_keys=True, default=str))
    else:
        click.echo(render_status(report))
    return 0


@cli.command("tasks")
def tasks_cmd() -> None:
    """What each task does, and what it fills."""
    from utmelab_bank.task import all_tasks, get

    for name in all_tasks():
        plugin = get(name)
        click.echo(f"{name}")
        click.echo(f"  fills      {plugin.produces}")
        click.echo(f"  needs      {', '.join(plugin.requires) or 'nothing'}")
        click.echo(f"  ready lane {'yes' if plugin.may_write_ready else 'no'}")
        click.echo(f"  {plugin.description}")


@cli.command("selectors")
def selectors_cmd() -> None:
    """Every selector phrase the ``--where`` flag understands."""
    from utmelab_bank.store import all_names, describe

    for name in all_names():
        selector = describe(name)
        fills = f" (fills {', '.join(selector.fills)})" if selector.fills else ""
        click.echo(f"  {name:<22} {selector.description}{fills}")


@cli.command("config")
@click.option("--target", default="work")
@click.option("--sink", type=click.Choice(["db", "json"]), default=None)
@click.option("--local-database", type=click.Path(path_type=Path), default=None)
def config_cmd(target: str, sink: str | None, local_database: Path | None) -> None:
    """Where every setting came from. ``default`` is how a CI typo shows up."""
    config = _config(target=target, sink=sink, local_database=local_database)
    for field, origin in sorted(config.source().items()):
        click.echo(f"  {field:<22} {origin}")
    click.echo("")
    click.echo(f"  repo root        {config.repo.path}")
    click.echo(f"  rust schema      {config.repo.rust_schema}")
    click.echo(f"  var directory    {config.repo.var}")


@_command("contract")
@click.option("--deep", is_flag=True, help="Also count rows and name never-written columns.")
@_add_common
def contract_cmd(
    deep: bool,
    target: str,
    sink: str | None,
    local_database: Path | None,
    log_level: str | None,  # noqa: ARG001
) -> None:
    """Compare the database against what the API says it reads."""
    raise SystemExit(
        asyncio.run(_contract(deep=deep, target=target, sink=sink, local_database=local_database))
    )


async def _contract(
    *, deep: bool, target: str, sink: str | None, local_database: Path | None
) -> int:
    from utmelab_bank.contract import check_shapes, load_contract, read_contract_version
    from utmelab_bank.store.schema import ensure_schema

    config = _config(target=target, sink=sink, local_database=local_database)
    contract = load_contract(config.repo.rust_schema)
    click.echo(f"contract version declared by the api: {contract.contract_version}")
    click.echo(f"tables the api says it reads:          {len(contract.read_shapes)}")
    click.echo(f"  of those, created by the api:        {len(contract.owned_tables)}")
    click.echo(f"  of those, ours to create:            {len(contract.borrowed_tables)}")

    async with _open(config) as store:
        await ensure_schema(store)
        stamped = await read_contract_version(store)
        click.echo(f"contract version stamped in the bank: {stamped}")
        if stamped is None:
            click.echo(
                "  nothing has stamped one, so this package would refuse to write. "
                "The api stamps it on first boot.",
                err=True,
            )
        report = await check_shapes(store, contract, deep=deep)

    for table in report.missing_tables:
        owner = "api creates it" if table in contract.owned_tables else "the bank creates it"
        click.echo(f"  missing table   {table:<22} {owner}", err=True)
    for column in report.missing_columns:
        click.echo(f"  missing column  {column}", err=True)
    for column in report.never_written:
        click.echo(f"  never written   {column}", err=True)

    reason = report.reason()
    if reason is None:
        click.echo("shapes agree")
        return 0
    click.echo(reason, err=True)
    return 1


@cli.command("explain")
@click.argument("expression")
def explain_cmd(expression: str) -> None:
    """What a ``--where`` expression selects, in words."""
    from utmelab_bank.store import explain, resolve

    try:
        resolved = resolve(expression)
    except BankError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc
    click.echo(f"  selects   {explain(expression)}")
    click.echo(f"  sql       {resolved.clause or 'every row'}")
    for key, value in sorted(resolved.params.items()):
        click.echo(f"  {key:<12} {value}")


@contextlib.asynccontextmanager
async def _open(config: Config) -> AsyncIterator[Any]:
    """Open the configured database, or refuse before any work starts.

    An async context manager rather than a plain call, because every command
    that touches storage has to close what it opened. The pipeline leaked a
    sqlite handle on each of its early returns.
    """
    if config.sink == "json":
        yield _NullStore()
        return
    store = await Store.open(config.require_database(), config.database_token)
    try:
        yield store
    finally:
        await store.aclose()


class _NullStore:
    """A stand in for the database when the sink is json.

    Present so a task written against the repository runs unchanged in the
    development mode, rather than needing a second code path that is never
    exercised.
    """

    async def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def execute_many(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def fetch_all(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def fetch_one(self, *_args: Any, **_kwargs: Any) -> dict[str, Any] | None:
        return None

    async def scalar(self, *_args: Any, **_kwargs: Any) -> Any:
        return 0

    async def aclose(self) -> None:
        return None


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns an exit code rather than raising, so the console
    script and ``python -m`` behave identically."""
    try:
        cli.main(args=argv, standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.Abort:
        click.echo("aborted", err=True)
        return 130
    except BankError as exc:
        click.echo(f"{exc.code}: {exc}", err=True)
        return 1
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
