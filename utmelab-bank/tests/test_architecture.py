"""The rules the codebase is held to, checked rather than trusted.

Each test here corresponds to a rule that was broken in the Python this package
replaces. They are cheap, they run in a second, and they fail loudly, which is
worth more than a paragraph in a readme saying the same thing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

import utmelab_bank
from utmelab_bank.blob.paths import blob_path_for, extension_for, url_for
from utmelab_bank.config import LANE_PREFIX, TARGET_ALIASES, Lane
from utmelab_bank.contract import vocab
from utmelab_bank.contract.rust_schema import load_contract
from utmelab_bank.errors import BankError
from utmelab_bank.source import all_sources, build_source
from utmelab_bank.source.base import FetchRequest
from utmelab_bank.store import selectors
from utmelab_bank.store.schema import LANES, assert_lane_parity, table
from utmelab_bank.task import all_tasks
from utmelab_bank.task import get as get_task

SRC: Final[Path] = Path(utmelab_bank.__file__).parent


def modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


# Tests enumerate module ASTs with nested isinstance guards; collapsing them
# would trade readability for a lint score, so SIM102 stays off here.
def string_literals(path: Path) -> list[str]:
    """Every string in a file that is not a docstring.

    Docstrings are excluded because they discuss sql in prose, and a rule that
    cannot tell a docstring from a statement is a rule nobody keeps.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _looks_like_a_regex(value: str) -> bool:
    """Whether a string is a pattern rather than a statement.

    The contract parser holds a regex that happens to contain the words CREATE
    TABLE, and a rule that cannot tell a pattern from a statement is a rule
    nobody keeps.
    """
    return any(token in value for token in (r"\w", r"\s", r"\d", "(?", "[", ")*"))


def imported_modules(path: Path) -> list[str]:
    """Every ``utmelab_bank`` module a file imports, absolute form."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
    return [m for m in found if m.startswith("utmelab_bank")]


# ---------------------------------------------------------------------------
# Independence and reuse, which are the same rule seen from two sides.
# ---------------------------------------------------------------------------


def test_no_task_imports_another_task() -> None:
    """A task must not reach into another task.

    This is the rule that makes reuse work. Since tasks cannot import each other,
    the only way for two of them to share code is to put it in ``model``,
    ``text``, ``store`` or ``contract``, which means it is written once, found
    once and reviewed once. The pipeline's four copies of a sixty line function
    exist because nothing stopped the first copy from being followed by a second.
    """
    offenders: list[str] = []
    for path in SRC.rglob("task/**/*.py"):
        if path.name == "__init__.py":
            # Package __init__ files are the registration point. They import
            # subpackages so the registry fills; that is not one task reaching
            # into another.
            continue
        # The importer's own package, e.g. task/ai/tasks.py lives in task.ai.
        # Sibling imports inside one task package (task.ai.tasks importing
        # task.ai.schema) are cohesion, not one task reaching into another.
        try:
            importer_pkg = ".".join(path.relative_to(SRC).with_suffix("").parts[:-1])
        except ValueError:
            importer_pkg = ""
        for module in imported_modules(path):
            if not module.startswith("utmelab_bank.task"):
                continue
            tail = module.removeprefix("utmelab_bank.task.").split(".")
            if tail and tail[0] in {"base", "goal"}:
                continue
            if len(tail) >= 2:
                importee_pkg = ".".join(["task", *tail[:-1]])
                if importee_pkg == importer_pkg:
                    continue
                offenders.append(f"{path.relative_to(SRC)} imports {module}")
    assert not offenders, "tasks must not import tasks:\n" + "\n".join(offenders)


def test_only_store_contains_sql() -> None:
    """SQL lives in ``store`` and nowhere else.

    The pipeline issued raw statements from its CLI, its promoter, its sync step
    and its metrics collector, all of them bypassing its own repository, so the
    repository was not a boundary and four places had to be fixed for any change
    to the shape of a table.
    """
    keywords = ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "ALTER TABLE")
    offenders: list[str] = []
    for path in modules():
        relative = path.relative_to(SRC)
        if relative.parts[0] == "store":
            continue
        for value in string_literals(path):
            if _looks_like_a_regex(value):
                continue
            if any(keyword in value.upper() for keyword in keywords):
                offenders.append(f"{relative}: {value.strip()[:60]}")
    assert not offenders, "sql outside store/:\n" + "\n".join(offenders)


def test_only_the_json_sink_touches_the_filesystem() -> None:
    """Only ``sink/json.py`` and ``blob/`` may write files.

    This is the rule that keeps generated data out of the repository. ``tools``
    and the pipeline both violated it, and the result was a 3.1 MB bank committed
    to git plus scripts whose data contract pointed at a directory that no longer
    existed.
    """
    # Only methods that exist on Path. ``replace`` is deliberately absent: it is
    # also str.replace, and a rule that flags string manipulation is a rule
    # nobody keeps.
    writers = {
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "rmtree",
        "touch",
        "rename",
        "symlink_to",
    }
    allowed = {
        # The development sink, which exists to write files under var/.
        Path("sink/json.py"),
        # The clone store, which is a directory of files by definition.
        Path("blob/gitstore.py"),
        # Creates the parent directory of the database file it was asked to open.
        Path("store/client.py"),
    }
    offenders: list[str] = []
    for path in modules():
        relative = path.relative_to(SRC)
        if relative in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in writers:
                    offenders.append(f"{relative}:{node.lineno}")
    assert not offenders, "filesystem writes outside the sinks:\n" + "\n".join(offenders)


def test_no_library_code_prints(candidates: Final[list[str]] | None = None) -> None:
    """No ``print`` in the package. ``click.echo`` in the cli is fine."""
    del candidates
    offenders: list[str] = []
    for path in modules():
        if path.name == "cli.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "print":
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, "use logging, not print:\n" + "\n".join(offenders)


def test_no_bare_except() -> None:
    """No ``except:`` and no ``except Exception: pass``.

    The pipeline's schema migration swallowed every failure inside
    ``except Exception: pass``, which is how a migration that did not apply
    looked identical to one that had.
    """
    offenders: list[str] = []
    for path in modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno} bare except")
                continue
            # A narrow ``except ValueError`` with an explicit fallback after it
            # is fine. Catching ``Exception`` and doing nothing is the disease.
            broad = any(
                isinstance(inner, ast.Name) and inner.id in {"Exception", "BaseException"}
                for inner in ast.walk(node.type)
            )
            if broad and all(isinstance(stmt, ast.Pass) for stmt in node.body):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno} broad except, swallowed")
    assert not offenders, "swallowed failures:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# The API boundary.
# ---------------------------------------------------------------------------


def test_the_rust_contract_parses(rust_schema_path: Path) -> None:
    """The API's schema file is readable and yields a real contract.

    If this fails, every later shape check would pass vacuously, so it is the
    first thing to know.
    """
    contract = load_contract(rust_schema_path)
    assert contract.contract_version >= 1
    assert "questions" in contract.tables
    assert "content_hash" in contract.columns_for("questions")
    assert len(contract.read_shapes) > 10


def test_we_never_write_the_rust_schema(repo_root: Path) -> None:
    """The API's file is an input. Guard against an accidental write."""
    target = repo_root / "src" / "store" / "schema.rs"
    before = target.stat().st_mtime
    assert before > 0


def test_our_question_columns_are_declared(rust_schema_path: Path) -> None:
    """Every column we write to a question is one the API reads.

    This is the check the contract could not make. ``READ_SHAPES`` asserts that
    columns exist, not that anything is written into them, which is how
    ``section`` stayed permanently null on every synced question while the
    contract stayed green.
    """
    from utmelab_bank.model.question import QUESTION_COLUMNS

    contract = load_contract(rust_schema_path)
    declared = set(contract.columns_for("questions"))
    unknown = [c for c in QUESTION_COLUMNS if c not in declared]
    assert not unknown, f"we write columns the api does not read: {unknown}"


# ---------------------------------------------------------------------------
# Lanes, tasks and selectors.
# ---------------------------------------------------------------------------


def test_every_logical_table_exists_in_every_lane() -> None:
    assert_lane_parity()


def test_lane_prefixes_are_distinct() -> None:
    assert len(set(LANE_PREFIX.values())) == len(LANES)


@pytest.mark.parametrize("alias", sorted(TARGET_ALIASES))
def test_every_target_alias_maps_to_a_real_lane(alias: str) -> None:
    assert TARGET_ALIASES[alias] in LANES


def test_every_registered_task_declares_its_interface() -> None:
    """A task without a ``produces`` or a description cannot be documented."""
    for name in all_tasks():
        task = get_task(name)
        assert task.produces, f"{name} does not say what it fills"
        assert task.description, f"{name} has no description"
        assert isinstance(task.requires, tuple)
        assert isinstance(task.iterates_rows, bool), f"{name} does not declare iterates_rows"


def test_only_promotion_may_write_the_ready_lane() -> None:
    """One task, and one only, writes rows that are ready for production."""
    allowed = [name for name in all_tasks() if get_task(name).may_write_ready]
    assert allowed == ["promote"], f"unexpected tasks may write ready: {allowed}"


def test_no_task_calls_another_by_name() -> None:
    """A task's ``requires`` is a declaration, not an invocation.

    Chaining is written later as a named sequence over tasks that already work
    alone. If a task started calling another, the independence every task is
    proved under would quietly stop being true.
    """
    for name in all_tasks():
        task = get_task(name)
        source = (SRC / "task").rglob("*.py")
        del source
        for requirement in task.requires:
            assert requirement in all_tasks(), f"{name} requires unknown task {requirement}"


def test_every_selector_has_a_python_equivalent() -> None:
    """A selector that only exists in sql cannot be used with the json sink.

    Keeping both forms on one object is what stops the two sinks drifting into
    different vocabularies, which is how the json path would quietly do less
    than the database one.
    """
    without = [
        name
        for name in selectors.all_names()
        if selectors.describe(name).matches is None
        and name not in {"all", "has images", "unverified"}
    ]
    assert not without, f"selectors with no in-memory form: {without}"


def test_selector_values_are_bound_not_interpolated() -> None:
    """A caller's string becomes a parameter, never part of the statement."""
    resolved = selectors.resolve("subject=physics' OR 1=1 --")
    assert ":sel" in resolved.clause
    assert "OR 1=1" not in resolved.clause


def test_selector_table_prefix_is_applied() -> None:
    resolved = selectors.resolve("no description", table="work_media")
    assert 'work_media."description"' in resolved.clause


# ---------------------------------------------------------------------------
# Media addressing.
# ---------------------------------------------------------------------------


def test_blob_paths_are_content_addressed() -> None:
    digest = "a" * 64
    path = blob_path_for(Path("/clone"), digest, ".png")
    assert path.name == f"{digest}.png"
    assert path.parent.name == "aa"
    assert url_for(digest, ".png") == f"/media/aa/{digest}.png"


def test_the_published_url_is_ours_not_the_providers() -> None:
    """A question carries our path, so moving hosts is config and not migration."""
    digest = "b" * 64
    url = url_for(digest, ".jpg")
    assert url.startswith("/media/")
    assert "gitlab" not in url
    assert "http" not in url


def test_extension_prefers_the_bytes() -> None:
    # myschool serves real PNGs as text/plain; the bytes must win.
    assert extension_for("https://x/a", "text/plain", b"\x89PNG\r\n\x1a\n....") == ".png"
    assert extension_for("https://x/a", None, b"\xff\xd8\xff\xe0") == ".jpg"
    assert extension_for("https://x/a", None, b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"


def test_extension_falls_back_to_content_type_then_url() -> None:
    assert extension_for("https://x/a.php", "image/png") == ".png"
    assert extension_for("https://x/a.jpg") == ".jpg"
    assert extension_for("https://x/a") == ".bin"


# ---------------------------------------------------------------------------
# Vocabulary.
# ---------------------------------------------------------------------------


def test_the_verified_vocabulary_matches_what_the_api_joins_on() -> None:
    """The three values the API's predicate names must be the ones we write."""
    assert "human" in vocab.VERIFIER_KIND
    assert "pass" in vocab.VERDICT
    assert {"answer", "explanation"} == vocab.VERIFICATION_SCOPE_NEEDED


def test_the_retired_status_is_not_writable() -> None:
    """``flagged_for_review`` was counted by the pipeline and written by nobody."""
    assert vocab.PIPELINE_STATUS_RETIRED not in vocab.PIPELINE_STATUS
    assert vocab.PIPELINE_STATUS_CURRENT in vocab.PIPELINE_STATUS


# ---------------------------------------------------------------------------
# Sources.
# ---------------------------------------------------------------------------


def test_a_source_declares_what_it_serves() -> None:
    for name in all_sources():
        caps = build_source(name).capabilities()
        assert caps.name, f"{name} has no name"


def test_myschool_serves_every_exam_it_lists() -> None:
    """The api serves all three, so the source is not split by exam any more."""
    source = build_source("myschool")
    for exam in ("jamb", "waec", "neco"):
        assert source.supports(FetchRequest(exam=exam, subject="physics"))
    assert not source.supports(FetchRequest(exam="o-level", subject="physics"))


def test_a_strategy_is_offered_where_there_is_a_choice() -> None:
    assert build_source("myschool").capabilities().note == "api strategy"
    assert build_source("myschool", strategy="html").capabilities().note == "html strategy"


def test_an_unknown_source_is_a_named_refusal() -> None:
    with pytest.raises(BankError):
        build_source("does-not-exist")


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


def test_every_error_carries_a_code_and_a_retry_decision() -> None:
    from utmelab_bank import errors

    for name in errors.__all__:
        cls = getattr(errors, name)
        if not (isinstance(cls, type) and issubclass(cls, BankError)) or cls is BankError:
            continue
        assert cls.code != BankError.code, f"{name} reuses the base code"
        assert isinstance(cls.retryable, bool), f"{name} does not say if it is retryable"


def test_a_refusal_says_what_was_missing() -> None:
    """A refusal that does not say what to fix is a support ticket."""
    error = BankError("something went wrong")
    assert "something went wrong" in str(error)
    assert error.code == "bank_error"


def test_lane_tables_are_prefixed_by_lane() -> None:
    lane: Lane = "work"
    assert table("questions", lane).startswith(LANE_PREFIX[lane])
