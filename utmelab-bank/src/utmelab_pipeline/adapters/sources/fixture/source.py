"""A source adapter that reads recorded JSON fixtures."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from utmelab_pipeline.domain.enums import MarkKind, Severity
from utmelab_pipeline.domain.hashing import payload_hash
from utmelab_pipeline.domain.models.common import (
    CatalogRef,
    CatalogSnapshot,
    CatalogTopic,
    CatalogSubtopic,
    Content,
    Coverage,
    Issue,
    Mark,
    MediaRef,
    Option,
    Passage,
    Provenance,
    RichText,
    Scope,
    SourceCapabilities,
    SourceItem,
    SourceProfile,
    StagingItem,
)


class FixtureSource:
    """Reads one JSON file per scope from a fixture directory."""

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
        fetched_at = self._fetched_at(record)
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

    def adapt(self, item: SourceItem, catalog: CatalogSnapshot) -> StagingItem:
        """Adapt raw source item to staging item using production catalog snapshot."""
        payload = item.payload
        catalog_snapshot = catalog
        topic_id = payload.get("topic_id")
        subtopic_id = payload.get("subtopic_id")
        if not isinstance(topic_id, str) or not isinstance(subtopic_id, str):
            raise ValueError("payload must name topic_id and subtopic_id")
        subtopic = next((s for s in catalog_snapshot.subtopics if s.id == subtopic_id), None)
        if subtopic is None or subtopic.topic_id != topic_id:
            raise ValueError(f"catalog has no subtopic {subtopic_id!r} under topic {topic_id!r}")

        raw_options = payload.get("options")
        if not isinstance(raw_options, list):
            raise ValueError("payload options must be a list")
        options = tuple(self._option(raw) for raw in raw_options)

        raw_marks = payload.get("marks")
        if isinstance(raw_marks, bool) or not isinstance(raw_marks, (int, float)):
            raise ValueError("payload marks must be a number")

        answer = payload.get("answer")
        if not isinstance(answer, str):
            raise ValueError("payload answer must be a string")

        explanation = payload.get("explanation")
        source_explanation = (
            self._rich_text(explanation, payload.get("explanation_marks"))
            if explanation is not None
            else None
        )

        raw_media = payload.get("media", [])
        if not isinstance(raw_media, list):
            raise ValueError("payload media must be a list")
        media_refs = tuple(self._media_ref(raw) for raw in raw_media)

        content = Content(
            stem=self._rich_text(payload.get("stem"), payload.get("stem_marks")),
            options=options,
            answer=answer,
            marks=float(raw_marks),
            passage=self._passage(payload.get("passage")),
            source_explanation=source_explanation,
            section=item.scope.section,
        )

        catalog_ref = CatalogRef(
            exam=item.scope.exam,
            subject=item.scope.subject,
            year=item.scope.year,
            section=item.scope.section,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            catalog_version=catalog_snapshot.version,
        )

        return StagingItem(
            id=item.external_key,
            provenance=Provenance(
                source=item.source,
                source_url=item.source_url,
                source_item_id=item.source_item_id,
                fetched_at=item.fetched_at,
                payload_hash=item.payload_hash,
                source_version=item.source_version,
                scope=item.scope,
            ),
            content=content,
            media_refs=tuple(self._media_ref(raw) for raw in payload.get("media", [])),
            catalog=CatalogRef(
                exam=item.scope.exam,
                subject=item.scope.subject,
                year=item.scope.year,
                section=item.scope.section,
                topic_id=payload.get("topic_id", ""),
                subtopic_id=payload.get("subtopic_id", ""),
                catalog_version=catalog_snapshot.version,
            ),
            state="adapted",
            created_at=item.fetched_at,
            updated_at=item.fetched_at,
        )

    def validate(self, item: SourceItem) -> list[str]:
        payload = item.payload
        issues: list[str] = []

        stem = payload.get("stem")
        if not isinstance(stem, str) or not stem.strip():
            issues.append("source.stem: stem is missing")

        option_ids = self._check_options(payload.get("options"))
        issues.extend(self._check_answer(payload.get("answer"), option_ids))
        media_keys = self._check_media(payload.get("media", []))
        issues.extend(self._check_stem_marks(payload.get("stem_marks", []), media_keys))
        return issues

    def _check_options(self, raw_options: object) -> list[str]:
        option_ids: list[str] = []
        if not isinstance(raw_options, list) or len(raw_options) < 2:
            return option_ids
        for raw in raw_options:
            if not isinstance(raw, dict):
                continue
            option_id = raw.get("id")
            text = raw.get("text")
            if isinstance(option_id, str) and isinstance(text, str) and text.strip():
                option_ids.append(option_id)
        return option_ids

    def _check_answer(self, answer: object, option_ids: list[str]) -> list[str]:
        issues: list[str] = []
        if not isinstance(answer, str) or not answer.strip():
            return ["source.answer: answer is missing"]
        elif answer not in option_ids:
            return ["source.answer: answer is not one of the options"]
        return []

    def _check_media(self, raw_media: object) -> list[str]:
        media_keys: list[str] = []
        if not isinstance(raw_media, list):
            return media_keys
        for raw in raw_media:
            if not isinstance(raw, dict):
                continue
            key = raw.get("key")
            url = raw.get("url")
            if isinstance(key, str) and isinstance(url, str):
                media_keys.append(key)
        return media_keys

    def _check_stem_marks(self, raw_marks: object, media_keys: list[str]) -> list[str]:
        issues: list[str] = []
        if not isinstance(raw_marks, list):
            return issues
        for index, raw in enumerate(raw_marks):
            if not isinstance(raw, dict):
                continue
            if raw.get("kind") == MarkKind.IMAGE.value:
                key = raw.get("asset_key")
                if not isinstance(key, str) or key not in media_keys:
                    issues.append(f"source.mark: stem mark {index} references an unknown media key")
        return issues

    def _option(self, raw: object) -> Option:
        if not isinstance(raw, dict):
            raise ValueError("option must be an object")
        option_id = raw.get("id")
        text = raw.get("text")
        if not isinstance(option_id, str) or not isinstance(text, str):
            raise ValueError("option needs an id and text")
        from utmelab_pipeline.domain.models.common import Option, RichText
        return Option(id=option_id, text=self._rich_text(text, raw.get("marks")))

    def _passage(self, raw: object) -> Passage | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("passage must be an object")
        passage_id = raw.get("id")
        text = raw.get("text")
        source_item_id = raw.get("source_item_id")
        if not isinstance(passage_id, str) or not isinstance(text, str):
            raise ValueError("passage needs an id and text")
        if source_item_id is not None and not isinstance(source_item_id, str):
            raise ValueError("passage source_item_id must be a string")
        from utmelab_pipeline.domain.models.common import Passage, RichText
        return Passage(
            id=passage_id,
            text=self._rich_text(text, raw.get("marks")),
            source_item_id=source_item_id,
        )

    def _media_ref(self, raw: object) -> MediaRef:
        if not isinstance(raw, dict):
            raise ValueError("media entry must be an object")
        key = raw.get("key")
        url = raw.get("url")
        if not isinstance(key, str) or not isinstance(url, str):
            raise ValueError("media entry needs a key and url")
        mime = raw.get("mime")
        alt = raw.get("alt")
        required = raw.get("required", False)
        if mime is not None and not isinstance(mime, str):
            raise ValueError("media mime must be a string")
        if alt is not None and not isinstance(alt, str):
            raise ValueError("media alt must be a string")
        if not isinstance(required, bool):
            raise ValueError("media required must be a boolean")
        return MediaRef(key=key, source_url=url, mime=mime, alt=alt, required=required)

    def _rich_text(self, text: object, raw_marks: object) -> RichText:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("rich text must be a non-empty string")
        marks: list[Mark] = []
        if raw_marks is not None:
            if not isinstance(raw_marks, list):
                raise ValueError("marks must be a list")
            for raw in raw_marks:
                marks.append(self._mark(raw))
        from utmelab_pipeline.domain.models.common import RichText
        return RichText(text=text, marks=tuple(marks))

    def _mark(self, raw: object) -> Mark:
        if not isinstance(raw, dict):
            raise ValueError("mark must be an object")
        kind = raw.get("kind")
        start = raw.get("start")
        length = raw.get("length")
        asset_key = raw.get("asset_key")
        if not isinstance(kind, str):
            raise ValueError("mark kind must be a string")
        if isinstance(start, bool) or not isinstance(start, int):
            raise ValueError("mark start must be an integer")
        if isinstance(length, bool) or not isinstance(length, int):
            raise ValueError("mark length must be an integer")
        if asset_key is not None and not isinstance(asset_key, str):
            raise ValueError("mark asset_key must be a string")
        return Mark(kind=kind, start=start, length=length, asset_id=asset_key)

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

    def _parse_catalog_snapshot(self, catalog: CatalogSnapshot) -> CatalogSnapshot:
        return catalog