"""The bank's own database. The one place that writes staging rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Optional

from utmelab_pipeline.domain.enums import State
from utmelab_pipeline.domain.models import StagingItem
from utmelab_pipeline.domain.state import InvalidTransition, can_transition

from .schema import ensure_schema


class StagingStore:
    """Reads and writes staging rows in the bank database."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def prepare(self) -> None:
        """Create the table if it is missing."""
        await ensure_schema(self._client)

    async def save(self, item: StagingItem) -> None:
        """Write a staging row, replacing any earlier version of it."""
        await self._client.execute(
            """
            INSERT OR REPLACE INTO staging_items (
                id, state, exam, subject, year, source, source_item_id,
                source_url, payload_hash, content_hash, bundle_hash,
                content, catalog, media, evidence, attempts, error,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                item.id,
                item.state.value,
                item.provenance.scope.exam,
                item.provenance.scope.subject,
                item.provenance.scope.year,
                item.provenance.source,
                item.provenance.source_item_id,
                str(item.provenance.source_url),
                item.provenance.payload_hash,
                item.hashes.content_hash if item.hashes else "",
                item.hashes.bundle_hash if item.hashes else "",
                item.content.model_dump_json(),
                item.catalog.model_dump_json() if item.catalog else None,
                json.dumps([asset.model_dump(mode="json") for asset in item.media_assets]),
                json.dumps(_evidence(item)),
                item.attempts,
                item.error,
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
            ],
        )

    async def load(self, item_id: str) -> Optional[StagingItem]:
        """Read one staging row."""
        result = await self._client.execute(
            "SELECT id, state, exam, subject, year, source, source_item_id, "
            "source_url, payload_hash, content_hash, bundle_hash, content, "
            "catalog, media, evidence, attempts, error, created_at, updated_at "
            "FROM staging_items WHERE id = ?",
            [item_id],
        )
        if not result.rows:
            return None
        return _row_to_item(result.rows[0])

    async def transition(
        self,
        item_id: str,
        expected: str,
        target: str,
        *,
        error: Optional[str] = None,
    ) -> StagingItem:
        """Move a row to a new state. The state machine refuses a wrong move."""
        item = await self.load(item_id)
        if item is None:
            raise KeyError(f"no staging row {item_id!r}")
        if item.state.value != expected:
            raise InvalidTransition(
                f"row is {item.state.value}, not {expected}"
            )
        resolved = State(target)
        if not can_transition(item.state, resolved):
            raise InvalidTransition(
                f"cannot move from {item.state.value} to {resolved.value}"
            )
        moved = item.transition_to(resolved, error=error)
        await self.save(moved)
        return moved

    async def list_by_state(
        self,
        state: str,
        *,
        limit: int = 100,
    ) -> tuple[StagingItem, ...]:
        """Read the rows in one state."""
        result = await self._client.execute(
            "SELECT id, state, exam, subject, year, source, source_item_id, "
            "source_url, payload_hash, content_hash, bundle_hash, content, "
            "catalog, media, evidence, attempts, error, created_at, updated_at "
            "FROM staging_items WHERE state = ? ORDER BY created_at LIMIT ?",
            [state, limit],
        )
        return tuple(_row_to_item(row) for row in result.rows)


def _evidence(item: StagingItem) -> dict[str, Any]:
    return {
        "image_descriptions": [
            d.model_dump(mode="json") for d in item.evidence.image_descriptions
        ],
        "tag": item.evidence.tag.model_dump(mode="json") if item.evidence.tag else None,
        "explanation": (
            item.evidence.explanation.model_dump(mode="json")
            if item.evidence.explanation
            else None
        ),
        "answer_verdict": (
            item.evidence.answer_verdict.model_dump(mode="json")
            if item.evidence.answer_verdict
            else None
        ),
        "gate": item.evidence.gate.model_dump(mode="json") if item.evidence.gate else None,
        "verifications": [
            v.model_dump(mode="json") for v in item.evidence.verifications
        ],
    }


def _row_to_item(row: tuple[Any, ...]) -> StagingItem:
    from utmelab_pipeline.domain.models import (
        CatalogRef,
        Content,
        Evidence,
        Hashes,
        MediaAsset,
        Provenance,
        Scope,
        Verification,
    )
    from utmelab_pipeline.domain.enums import State

    (
        item_id,
        state,
        exam,
        subject,
        year,
        source,
        source_item_id,
        source_url,
        payload_hash,
        content_hash,
        bundle_hash,
        content,
        catalog,
        media,
        evidence,
        attempts,
        error,
        created_at,
        updated_at,
    ) = row

    return StagingItem(
        id=item_id,
        provenance=Provenance(
            source=source,
            source_url=source_url,
            source_item_id=source_item_id,
            fetched_at=datetime.fromisoformat(created_at),
            payload_hash=payload_hash,
            source_version="1",
            scope=Scope(exam=exam, subject=subject, year=year),
        ),
        content=Content.model_validate_json(content),
        media_assets=tuple(
            MediaAsset.model_validate(asset) for asset in json.loads(media)
        ),
        evidence=Evidence.model_validate(json.loads(evidence)),
        catalog=CatalogRef.model_validate_json(catalog) if catalog else None,
        state=State(state),
        hashes=Hashes(
            payload_hash=payload_hash,
            content_hash=content_hash,
            bundle_hash=bundle_hash,
        ),
        attempts=attempts,
        error=error,
        created_at=datetime.fromisoformat(created_at),
        updated_at=datetime.fromisoformat(updated_at),
    )


__all__ = ["StagingStore"]
