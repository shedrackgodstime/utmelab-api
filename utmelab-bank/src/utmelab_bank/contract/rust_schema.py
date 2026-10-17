"""Read the API's declared shapes out of its Rust source.

``src/store/schema.rs`` is the single source of truth for production shapes.
Its module comment says it plainly: the pipeline stages whatever it wants in
its own tables, but what lands in production must match that file. So we parse
it rather than mirror it, because a mirror drifts the first time nobody updates
it, and a contract that has quietly drifted is worse than no contract at all.

The file is read as text and never written. Nothing here needs a Rust
toolchain, so the check runs identically in a terminal and in a workflow.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final, NamedTuple

from utmelab_bank.errors import ContractError

__all__ = ["ReadShape", "RustContract", "parse_schema_rs", "load_contract"]

_CONTRACT_VERSION: Final[re.Pattern[str]] = re.compile(
    r"pub\s+const\s+CONTRACT_VERSION\s*:\s*u64\s*=\s*(\d+)\s*;",
)

_READ_SHAPES_DECL: Final[re.Pattern[str]] = re.compile(
    r"pub\s+const\s+READ_SHAPES\s*:\s*&\[\(&str,\s*&\[&str\]\)\]\s*=\s*&\[",
)

_ENTRY_START: Final[re.Pattern[str]] = re.compile(r'\(\s*"([^"]+)"\s*,\s*&\[')

_STRING: Final[re.Pattern[str]] = re.compile(r'"([^"]*)"')


_DDL_DECL: Final[re.Pattern[str]] = re.compile(
    r"const\s+DDL\s*:\s*&\[&str\]\s*=\s*&\[(.*?)\n\];",
    re.DOTALL,
)

_CREATE_TABLE: Final[re.Pattern[str]] = re.compile(
    r"CREATE TABLE IF NOT EXISTS\s+(\w+)",
    re.IGNORECASE,
)


class ReadShape(NamedTuple):
    """One table and the columns the API says it reads."""

    table: str
    columns: tuple[str, ...]

    def missing_from(self, present: frozenset[str]) -> list[str]:
        """Columns the API needs that this table does not have."""
        return [c for c in self.columns if c not in present]


class RustContract(NamedTuple):
    """What the API declares it reads, extracted from its own source.

    ``owned_tables`` is the distinction that makes the report readable: those are
    the tables the API creates for itself at boot, and the rest are the bank
    tables it reads but leaves to us to create. A bank database is expected to
    have the first group only once the API has booted against it, and the second
    group always.
    """

    contract_version: int
    read_shapes: tuple[ReadShape, ...]
    path: Path
    owned_tables: tuple[str, ...] = ()

    def shape_for(self, table: str) -> ReadShape | None:
        for shape in self.read_shapes:
            if shape.table == table:
                return shape
        return None

    @property
    def tables(self) -> tuple[str, ...]:
        return tuple(s.table for s in self.read_shapes)

    @property
    def borrowed_tables(self) -> tuple[str, ...]:
        """Tables the API reads but does not create. Ours to provide."""
        return tuple(t for t in self.tables if t not in self.owned_tables)

    def columns_for(self, table: str) -> tuple[str, ...]:
        shape = self.shape_for(table)
        return shape.columns if shape else ()


def _parse_owned_tables(text: str) -> tuple[str, ...]:
    """The names in the API's own ``DDL`` list.

    Parsed because the report is only useful if it can say "these five are the
    API's and it will create them" rather than listing everything as missing.
    """
    block = _DDL_DECL.search(text)
    if block is None:
        return ()
    return tuple(_CREATE_TABLE.findall(block.group(1)))


def _matching_bracket(text: str, open_at: int) -> int:
    """The index of the bracket closing the one at ``open_at``.

    Brackets inside a string literal do not count, which matters because no
    column name contains one today and one might tomorrow.
    """
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_at, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
            if depth == 0:
                return index
    raise ContractError("an unclosed bracket in READ_SHAPES")


def _parse_shapes(text: str) -> tuple[ReadShape, ...]:
    """Every ``(table, [columns])`` entry, in declaration order.

    Bracket matching rather than one regex, because rustfmt puts a short entry
    on one line and a long one across forty, so any single pattern has to be
    right about both. This one is right about both by construction.
    """
    declaration = _READ_SHAPES_DECL.search(text)
    if declaration is None:
        raise ContractError("READ_SHAPES not found")

    block_start = declaration.end()
    block_end = _matching_bracket(text, block_start - 1)
    block = text[block_start:block_end]

    shapes: list[ReadShape] = []
    position = 0
    while True:
        entry = _ENTRY_START.search(block, position)
        if entry is None:
            break
        list_start = entry.end() - 1
        list_end = _matching_bracket(block, list_start)
        shapes.append(
            ReadShape(
                table=entry.group(1),
                columns=tuple(_STRING.findall(block[list_start + 1 : list_end])),
            )
        )
        position = list_end + 1

    return tuple(shapes)


def parse_schema_rs(text: str, path: Path) -> RustContract:
    """Extract the version and the read shapes.

    Raises :class:`ContractError` rather than returning something partial. A
    parser that silently found no shapes would let every later check pass
    vacuously, which is the one failure mode a contract must never have.
    """
    version_match = _CONTRACT_VERSION.search(text)
    if version_match is None:
        raise ContractError("CONTRACT_VERSION not found", path=str(path))

    shapes = _parse_shapes(text)
    if not shapes:
        raise ContractError("READ_SHAPES parsed to nothing", path=str(path))

    return RustContract(
        contract_version=int(version_match.group(1)),
        read_shapes=shapes,
        path=path,
        owned_tables=_parse_owned_tables(text),
    )


def load_contract(schema_path: Path) -> RustContract:
    """Read and parse the API's schema file."""
    if not schema_path.is_file():
        raise ContractError(
            "the API schema file is not where the config says it is",
            path=str(schema_path),
            hint="run from the repository root, or set --repo",
        )
    return parse_schema_rs(schema_path.read_text(encoding="utf-8"), schema_path)
