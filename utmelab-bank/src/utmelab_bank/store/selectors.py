"""Named selectors, so ``--where 'no description'`` means one thing per task.

The pipeline built its ``WHERE`` clause by string concatenation in three
modules, and every task that wanted rows built its own. So the vocabulary a
caller can use did not exist in one place, and a bug in one builder was a bug in
three.

Here a selector is a named predicate over a row. Each task registers the names
that make sense for what it produces, and the same phrase can mean different
things for different tasks without either being wrong. Nothing is built by
interpolation from user text: a selector resolves to a parameterised fragment
with its arguments bound.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from utmelab_bank.errors import StoreError
from utmelab_bank.model.base import now_iso

__all__ = [
    "Predicate",
    "Selector",
    "SelectorSet",
    "all_names",
    "explain",
    "is_known_column",
    "normalise",
    "register",
    "resolve",
]

#: A predicate receives the table prefix and the bound arguments, and returns a
#: sql fragment plus the parameters it needs. It never sees caller text.
Predicate = Callable[[dict[str, Any], tuple[Any, ...], str], tuple[str, dict[str, Any]]]


def _col(column: str) -> str:
    """Quote a column name.

    Only names from :data:`_COLUMNS` reach here, so quoting is belt and braces
    rather than the security boundary. The boundary is that a caller's string is
    never parsed into a column name.
    """
    if column not in _COLUMNS:
        raise StoreError("unknown column in selector", column=column)
    return f'"{column}"'


_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "id",
        "exam",
        "subject",
        "year",
        "source",
        "subtopic_id",
        "section",
        "passage_id",
        "answer",
        "content_hash",
        "fingerprint",
        "stem_key",
        "gate_status",
        "gate_reason",
        "run_id",
        "attempts",
        "next_retry_at",
        "status",
        "source_url",
        "question_id",
        "blob_path",
        "derived_path",
        "sha256",
        "media_url",
        "description",
        "description_model",
        "bytes",
        "kind",
        "verdict",
        "scope",
        "verifier",
        "text",
        "options",
        "inline",
        "explanation",
        "created_at",
        "updated_at",
    },
)


def is_known_column(name: str) -> bool:
    """Whether a name may appear as a column in a selector or an update."""
    return name in _COLUMNS


@dataclass(frozen=True)
class Selector:
    """One named predicate, plus a sentence saying what it picks.

    ``sql`` and ``matches`` are the same predicate in two languages. The
    database sink uses ``sql``; the json sink uses ``matches`` and refuses any
    selector that has no ``matches``, so a task written against the json sink
    cannot quietly do less than it would against the database. Keeping both on
    one object is what stops the two drifting into different vocabularies.
    """

    name: str
    description: str
    sql: Predicate
    #: Columns whose emptiness makes this selector true. Drives ``--explain``.
    fills: tuple[str, ...] = field(default=())
    #: An in-memory equivalent of ``sql``. ``None`` when the predicate needs
    #: something a row dict cannot answer.
    matches: Callable[[dict[str, Any], Any], bool] | None = None


def _absent(column: str) -> Callable[[dict[str, Any], Any], bool]:
    """A predicate matching rows where ``column`` holds nothing."""

    def check(row: dict[str, Any], _value: Any) -> bool:
        return row.get(column) in (None, "")

    return check


def _equals(column: str) -> Callable[[dict[str, Any], Any], bool]:
    def check(row: dict[str, Any], value: Any) -> bool:
        return str(row.get(column)) == str(value)

    return check


def _any_equal(column: str) -> Callable[[dict[str, Any], Any], bool]:
    def check(row: dict[str, Any], value: Any) -> bool:
        wanted = value if isinstance(value, list) else str(value).split(",")
        return str(row.get(column)) in {str(v).strip() for v in wanted}

    return check


def _and(*checks: Callable[[dict[str, Any], Any], bool]) -> Callable[[dict[str, Any], Any], bool]:
    def run(row: dict[str, Any], value: Any) -> bool:
        return all(check(row, value) for check in checks)

    return run


def _carries_image(row: dict[str, Any]) -> bool:
    """Whether a question row holds an image mark on its stem or its options.

    Both columns are json text, so the check is a substring probe rather than a
    parse. A parse would be more honest and would also be the slow path on every
    row of a 50 000 row scan, and the only question being asked is whether the
    word appears at all.
    """
    # json.dumps puts a space after the colon by default and jsonio does not,
    # so both spellings appear in a real database.
    needles = ('"kind":"image"', '"kind": "image"')
    for column in ("inline", "options"):
        value = row.get(column)
        if isinstance(value, str) and any(needle in value for needle in needles):
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("kind") == "image":
                    return True
                if isinstance(item, dict):
                    inner = item.get("text")
                    if isinstance(inner, dict) and inner.get("kind") == "image":
                        return True
    return False


_REGISTRY: Final[dict[str, Selector]] = {}


def register(selector: Selector) -> Selector:
    """Add a selector to the shared vocabulary."""
    if selector.name in _REGISTRY:
        raise StoreError("duplicate selector name", name=selector.name)
    _REGISTRY[selector.name] = selector
    return selector


def all_names() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def describe(name: str) -> Selector:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise StoreError(
            "unknown selector",
            name=name,
            known=all_names(),
        ) from exc


@dataclass(frozen=True)
class SelectorSet:
    """A resolved selector: the sql fragment and the arguments to bind."""

    clause: str
    params: dict[str, Any]

    @property
    def is_all(self) -> bool:
        return not self.clause


def resolve(expression: str, *, table: str | None = None) -> SelectorSet:
    """Turn ``'no description'`` or ``'has images and no description'`` into sql.

    The grammar is deliberately small: ``and`` joins terms, each term is a
    registered name optionally followed by ``=value``. No ``or``, no negation,
    no free sql. A selector language that grows a boolean grammar is a selector
    language someone will eventually inject through.

    ``table`` qualifies column references when the same predicate is used
    against a joined query. Names come from :data:`_COLUMNS` and values are
    bound as parameters, so a caller's string never becomes a column or a
    literal.
    """
    text = expression.strip().lower()
    if not text or text == "all":
        return SelectorSet(clause="", params={})

    prefix = f"{table}." if table else ""
    fragments: list[str] = []
    params: dict[str, Any] = {}

    for index, term in enumerate(t for t in (t.strip() for t in text.split(" and ")) if t):
        name, _, raw_value = term.partition("=")
        selector = describe(normalise(name))
        value: Any = raw_value.strip() if raw_value else None
        if value is not None:
            with contextlib.suppress(ValueError):
                value = int(value)

        clause, bound = selector.sql({}, (value,), prefix)
        for position, (key, bound_value) in enumerate(sorted(bound.items())):
            renamed = f"sel_{index}_{position}"
            clause = clause.replace(f":{key}", f":{renamed}")
            params[renamed] = bound_value
        fragments.append(f"({clause})")

    if not fragments:
        raise StoreError("selector expression matched nothing", expression=expression)

    return SelectorSet(clause=" AND ".join(fragments), params=params)


def explain(expression: str) -> str:
    """A human sentence for a selector, so ``--explain`` can answer plainly."""
    parts: list[str] = []
    for term in (t.strip() for t in expression.strip().lower().split(" and ")):
        if not term or term == "all":
            continue
        name = normalise(term.partition("=")[0])
        selector = describe(name)
        if selector.fills:
            parts.append(f"{name} ({', '.join(selector.fills)} empty)")
        else:
            parts.append(name)
    return " and ".join(parts) or "every row"


# ---------------------------------------------------------------------------
# The shared vocabulary. Registered here rather than inside each task so that
# two tasks cannot define the same phrase differently.
# ---------------------------------------------------------------------------

register(Selector("all", "every row in the lane", lambda _r, _a, _p: ("1=1", {})))
register(
    Selector(
        "subject",
        "rows for one subject, e.g. subject=physics",
        lambda _r, a, p: (f'{p}"subject" = :sel_value', {"sel_value": a[0]}),
        matches=_equals("subject"),
    )
)
register(
    Selector(
        "exam",
        "rows for one exam, e.g. exam=jamb",
        lambda _r, a, p: (f'{p}"exam" = :sel_value', {"sel_value": a[0]}),
        matches=_equals("exam"),
    )
)
register(
    Selector(
        "run",
        "rows written by one run, e.g. run=42",
        lambda _r, a, p: (f'{p}"run_id" = :sel_value', {"sel_value": a[0]}),
        matches=_equals("run_id"),
    )
)
register(
    Selector(
        "question id",
        "verifications for one question, e.g. question_id=q_42",
        lambda _r, a, p: (f'{p}"question_id" = :sel_value', {"sel_value": a[0]}),
        matches=_equals("question_id"),
    )
)


def _in_ids(_row: dict[str, Any], args: tuple[Any, ...], prefix: str) -> tuple[str, dict[str, Any]]:
    """``id IN (...)`` with one placeholder per element.

    The driver has no list expansion, so the placeholders are built here. The
    element count comes from the parsed list and never from the caller's text,
    so nothing a caller typed becomes part of the statement.
    """
    raw = args[0]
    wanted = raw if isinstance(raw, list) else str(raw).split(",")
    cleaned = [item.strip() for item in wanted if str(item).strip()]
    if not cleaned:
        return ("0=1", {})
    markers = ", ".join(f":sel_id_{index}" for index in range(len(cleaned)))
    params = {f"sel_id_{index}": value for index, value in enumerate(cleaned)}
    return (f'{prefix}"id" IN ({markers})', params)


register(
    Selector(
        "id",
        "one or more ids, comma separated",
        _in_ids,
        matches=_any_equal("id"),
    )
)
register(
    Selector(
        "gated",
        "rows that passed the mechanical gate",
        lambda _r, _a, p: (f"{p}\"gate_status\" = 'pass'", {}),
        fills=("gate_status",),
        matches=_equals("gate_status"),
    )
)
register(
    Selector(
        "no subtopic",
        "questions with no subtopic yet",
        lambda _r, _a, p: (f'{p}"subtopic_id" IS NULL', {}),
        fills=("subtopic_id",),
        matches=_absent("subtopic_id"),
    )
)
register(
    Selector(
        "no explanation",
        "questions with no explanation yet",
        lambda _r, _a, p: (f'{p}"explanation" IS NULL', {}),
        fills=("explanation",),
        matches=_absent("explanation"),
    )
)
register(
    Selector(
        "no description",
        "media rows a model has not described yet",
        lambda _r, _a, p: (
            f'({p}"description" IS NULL OR {p}"description" = \'\')',
            {},
        ),
        fills=("description",),
        matches=_absent("description"),
    )
)
register(
    Selector(
        "has images",
        "questions carrying at least one image mark",
        lambda _r, _a, p: (
            f'({p}"inline" LIKE \'%"kind":"image"%\' OR {p}"options" LIKE \'%"kind":"image"%\')',
            {},
        ),
        matches=lambda r, _v: _carries_image(r),
    )
)
register(
    Selector(
        "no blob",
        "media rows whose bytes are not in the clone yet",
        lambda _r, _a, p: (f'{p}"blob_path" IS NULL', {}),
        fills=("blob_path",),
        matches=_absent("blob_path"),
    )
)
register(
    Selector(
        "no media url",
        "media rows not yet pushed, and questions not yet given a media path",
        lambda _r, _a, p: (f'{p}"media_url" IS NULL', {}),
        fills=("media_url",),
        matches=_absent("media_url"),
    )
)
register(
    Selector(
        "not uploaded",
        "media rows the upload task has not finished with",
        lambda _r, _a, p: (f"{p}\"status\" <> 'uploaded'", {}),
        matches=lambda r, _v: str(r.get("status")) != "uploaded",
    )
)
register(
    Selector(
        "fetched",
        "media rows whose bytes are local",
        lambda _r, _a, p: (f"{p}\"status\" = 'fetched'", {}),
        matches=_equals("status"),
    )
)
register(
    Selector(
        "failed",
        "rows that failed a previous attempt",
        lambda _r, _a, p: (f'{p}"error" IS NOT NULL', {}),
        matches=lambda r, _v: bool(r.get("error")),
    )
)
register(
    Selector(
        "retryable",
        "failed rows whose next attempt is due",
        lambda _r, _a, p: (
            f'({p}"error" IS NOT NULL AND '
            f'({p}"next_retry_at" IS NULL OR {p}"next_retry_at" <= :sel_now))',
            {"sel_now": now_iso()},
        ),
        matches=lambda r, _v: (
            bool(r.get("error"))
            and (not r.get("next_retry_at") or str(r["next_retry_at"]) <= now_iso())
        ),
    )
)
register(
    Selector(
        "unverified",
        "questions with no human pass on the current content",
        lambda _r, _a, p: (
            "NOT EXISTS (SELECT 1 FROM verifications v WHERE v.question_id = "
            f"{p}\"id\" AND v.kind = 'human' AND v.verdict = 'pass' "
            f'AND v.content_hash = {p}"content_hash")',
            {},
        ),
    )
)

_RE_KEY = re.compile(r"[^a-z0-9]+")


def normalise(name: str) -> str:
    """Turn a phrase into a lookup key, so ``no-description`` finds ``no description``."""
    return _RE_KEY.sub(" ", name.strip().lower()).strip()
