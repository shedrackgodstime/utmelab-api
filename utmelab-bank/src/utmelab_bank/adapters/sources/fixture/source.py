"""A source adapter that reads recorded JSON fixtures."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from utmelab_bank.domain.hashing import payload_hash
from utmelab_bank.domain.models.common import (
    CatalogSnapshot,
    Coverage,
    Scope,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
    StagingItem,
)

from ..payload import adapt_payload, validate_payload


class FixtureSource:
    """Reads one JSON file per scope from a fixture directory."""

    #: The recorded fixture carries topic ids, so it cannot be adapted until
    #: the catalog says those ids exist. A live scraper sets this false.
    needs_catalog = True

    def __init__(self, fixture_dir: Path | str, *, source_name: str = "fixture") -> None:
        self._fixture_dir = Path(fixture_dir)
        if not self._fixture_dir.is_dir():
            raise ValueError(f"fixture directory does not exist: {self._fixture_dir}")
        self.profile = SourceProfile(
            name=source_name,
            version="1.0.0",
            exams=("JAMB",),
            subjects={"Biology": "Biology"},
            years=(2020, 2025),
            capabilities=SourceCapabilities(
                figures=True,
                rich_text=True,
                answer=True,
                sections=True,
                marks=True,
            ),
            rate_limit_per_second=1000.0,
        )

    async def probe(self, scope: Scope) -> Coverage:
        record = self._record(scope)
        raw_items = record.get("items") if record is not None else None
        if raw_items is None:
            item_count = 0
        elif isinstance(raw_items, list):
            item_count = len(raw_items)
        else:
            raise ValueError("fixture items must be a list")
        return Coverage(source=self.profile.name, scope=scope, item_count=item_count)

    async def fetch(self, scope: Scope) -> AsyncIterator[SourceItem]:
        record = self._record(scope)
        if record is None:
            return
        raw_items = record.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("fixture items must be a list")
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ValueError("fixture item must be an object")
            source_url = raw.get("source_url")
            source_item_id = raw.get("source_item_id")
            raw_scope = raw.get("scope")
            payload = raw.get("payload")
            if not isinstance(source_url, str) or not isinstance(source_item_id, str):
                raise ValueError("fixture item needs source_url and source_item_id")
            if not isinstance(payload, dict):
                raise ValueError("fixture payload must be an object")
            typed_payload = cast(dict[str, Any], payload)
            yield SourceItem(
                source=self.profile.name,
                source_url=source_url,
                source_item_id=source_item_id,
                fetched_at=self._fetched_at(record),
                payload=typed_payload,
                payload_hash=payload_hash(typed_payload),
                scope=Scope.model_validate(raw_scope),
                source_version=self.profile.version,
            )

    def adapt(self, item: SourceItem, catalog: CatalogSnapshot | None) -> StagingItem:
        """Adapt a recorded item. The fixture names its catalog entry already."""
        if catalog is None:
            raise ValueError("the fixture source needs a catalog to adapt a record")
        return adapt_payload(item, catalog)

    def validate(self, item: SourceItem) -> list[str]:
        return validate_payload(item.payload)

    def production_question_id(self, item: SourceItem) -> str | None:
        """Recorded fixtures do not claim a production ID."""
        return None

    def _record(self, scope: Scope) -> dict[str, Any] | None:
        path = self._path(scope)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"fixture must be an object: {path}")
        return cast(dict[str, Any], data)

    def _path(self, scope: Scope) -> Path:
        subject = re.sub(r"[^a-z0-9]+", "-", scope.subject.lower()).strip("-")
        return self._fixture_dir / f"{scope.exam.lower()}-{subject}-{scope.year}.json"

    def _fetched_at(self, record: dict[str, Any]) -> datetime:
        value = record.get("recorded_at")
        if not isinstance(value, str):
            raise ValueError("fixture is missing recorded_at")
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
