"""The JSON sink, for development only.

Its whole reason to exist is that the pipeline's first version wrote JSON and
that turned out to be a bad substrate: files in git, no transactions, no
selectors, and a data contract that outlived the directory the files lived in.

It stays, because being able to read a run's output without a database is worth
something. Three rules keep it from becoming the substrate again.

1. The only path it will write to is under ``var/``, which the repository
   ignores. Any other path is a refusal, not a warning.
2. It is never the default. ``--sink json`` is explicit or it does not happen.
3. It carries the lane in its path, so raw, work and ready output cannot land in
   each other's files.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from utmelab_bank.config import LANE_PREFIX, Config, Lane, RepoRoot
from utmelab_bank.errors import ConfigError
from utmelab_bank.model.base import now_iso
from utmelab_bank.store import selectors

__all__ = ["JsonSink", "refuse_outside_var"]


def refuse_outside_var(path: Path, repo: RepoRoot) -> Path:
    """Raise unless ``path`` is inside ``var/``.

    This is the single check that makes the guarantee true. Everything else in
    this module assumes it has run.
    """
    resolved = path.resolve()
    allowed = repo.var.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ConfigError(
            "the json sink may only write under var/",
            path=str(resolved),
            allowed=str(allowed),
            hint="the repository must never contain generated data",
        )
    return resolved


class JsonSink:
    """Writes one json file per logical table, per lane."""

    name = "json"

    def __init__(self, root: Path, repo: RepoRoot, lane: Lane = "work") -> None:
        self._root = refuse_outside_var(root, repo)
        self._repo = repo
        self._lane = lane

    @classmethod
    def from_config(cls, config: Config) -> JsonSink:
        return cls(config.repo.var / "bank", config.repo, lane=config.lane)

    def path_for(self, logical: str) -> Path:
        return self._root / f"{LANE_PREFIX[self._lane]}{logical}.json"

    async def write(self, logical: str, rows: list[dict[str, Any]]) -> int:
        target = refuse_outside_var(self.path_for(logical), self._repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = self._existing(logical)
        seen = {str(row.get("id")) for row in existing}
        merged = existing + [r for r in rows if str(r.get("id")) not in seen]
        target.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        return len(rows)

    async def read(self, logical: str, where: str = "all") -> list[dict[str, Any]]:
        """Filter in memory, using each selector's Python predicate.

        A selector with no predicate is refused rather than ignored, so a task
        written against the json sink cannot quietly do less than it would
        against the database.
        """
        rows = self._existing(logical)
        terms = self._terms(where)
        if not terms:
            return rows

        for name, _value in terms:
            selector = selectors.describe(name)
            if selector.matches is None:
                raise ConfigError(
                    "this selector needs the database",
                    selector=name,
                    hint="use --sink db for this task",
                )

        return [
            row
            for row in rows
            if all(selectors.describe(n).matches(row, v) for n, v in terms)  # type: ignore[misc]
        ]

    @staticmethod
    def _terms(where: str) -> list[tuple[str, Any]]:
        """Split an expression into ``(selector name, value)`` pairs."""
        text = where.strip().lower()
        if not text or text == "all":
            return []
        terms: list[tuple[str, Any]] = []
        for raw in (t.strip() for t in text.split(" and ")):
            if not raw:
                continue
            name, _, raw_value = raw.partition("=")
            value: Any = raw_value.strip() if raw_value else None
            if value is not None:
                with contextlib.suppress(ValueError):
                    value = int(value)
            terms.append((selectors.normalise(name), value))
        return terms

    def stamp(self, _logical: str) -> dict[str, Any]:
        """A small header file, so an output directory is self-describing."""
        return {
            "generated_at": now_iso(),
            "lane": self._lane,
            "sink": self.name,
            "tables": sorted(p.name for p in self._root.glob("*.json")),
        }

    async def close(self) -> None:
        return None

    def _existing(self, logical: str) -> list[dict[str, Any]]:
        target = self.path_for(logical)
        if not target.is_file():
            return []
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return list(payload) if isinstance(payload, list) else []
