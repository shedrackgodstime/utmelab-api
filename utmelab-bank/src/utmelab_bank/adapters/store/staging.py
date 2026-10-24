"""The bank's own database. The one place that writes staging rows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import Passage, StagingItem
from utmelab_bank.domain.state import InvalidTransition, can_transition

from .schema import ensure_schema

#: The staging columns in the order ``_row_to_item`` reads them. Kept in one
#: place so a new column cannot be added to the writer and forgotten by one of
#: the readers.
_COLUMNS = (
    "id, state, exam, subject, year, country, source, source_item_id, source_url, "
    "payload_hash, content_hash, bundle_hash, content, passage, catalog, media, "
    "evidence, attempts, error, created_at, updated_at, section, source_version, "
    "media_refs, media_blobs"
)


class StagingStore:
    """Reads and writes staging rows in the bank database."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def prepare(self) -> None:
        """Create the table if it is missing."""
        await ensure_schema(self._client)

    async def save(self, item: StagingItem) -> None:
        """Write a staging row, replacing any earlier version of it.

        A passage the item carries is written to the passages table as well,
        and written by id, so two questions that share one passage share one
        row.
        """
        if item.passage is not None:
            await self._save_passage(item.passage)
        await self._client.execute(
            """
            INSERT OR REPLACE INTO staging_items (
                id, state, exam, subject, year, country, source, source_item_id,
                source_url, payload_hash, content_hash, bundle_hash,
                content, passage, catalog, media, evidence, attempts, error,
                created_at, updated_at, section, source_version, media_refs, media_blobs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                item.id,
                item.state.value,
                item.provenance.scope.exam,
                item.provenance.scope.subject,
                item.provenance.scope.year,
                item.provenance.scope.country,
                item.provenance.source,
                item.provenance.source_item_id,
                str(item.provenance.source_url),
                item.provenance.payload_hash,
                item.hashes.content_hash if item.hashes else "",
                item.hashes.bundle_hash if item.hashes else "",
                item.content.model_dump_json(),
                item.passage.model_dump_json() if item.passage else None,
                item.catalog.model_dump_json() if item.catalog else None,
                json.dumps([asset.model_dump(mode="json") for asset in item.media_assets]),
                json.dumps(_evidence(item)),
                item.attempts,
                item.error,
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
                item.provenance.scope.section,
                item.provenance.source_version,
                json.dumps([ref.model_dump(mode="json") for ref in item.media_refs]),
                json.dumps({k: v.hex() for k, v in item.media_blobs.items()}),
            ],
        )

    async def _save_passage(self, passage: Passage) -> None:
        """Write one passage, keyed by its id so a shared passage is one row."""
        await self._client.execute(
            """
            INSERT OR REPLACE INTO passages (
                id, exam, subject, year, kind, title, author, text, inline,
                source_item_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                passage.id,
                passage.exam,
                passage.subject,
                passage.year,
                passage.kind.value,
                passage.title,
                passage.author,
                passage.text.text,
                json.dumps([mark.model_dump(mode="json") for mark in passage.text.inline]),
                passage.source_item_id,
            ],
        )

    async def passage_ids(self) -> frozenset[str]:
        """The ids of every passage the bank holds.

        This is the gate's known set, so a question naming a passage the bank
        has never seen is refused rather than trusted.
        """
        result = await self._client.execute("SELECT id FROM passages")
        return frozenset(str(row[0]) for row in result.rows)

    async def load_passage(self, passage_id: str) -> Passage | None:
        """Read one passage by id."""
        result = await self._client.execute(
            "SELECT id, exam, subject, year, kind, title, author, text, inline "
            "FROM passages WHERE id = ?",
            [passage_id],
        )
        if not result.rows:
            return None
        row = result.rows[0]
        from utmelab_bank.domain.enums import PassageKind
        from utmelab_bank.domain.models import RichText

        return Passage(
            id=str(row[0]),
            exam=str(row[1]),
            subject=str(row[2]),
            year=int(row[3]),
            kind=PassageKind(str(row[4])),
            title=str(row[5]) if row[5] is not None else None,
            author=str(row[6]) if row[6] is not None else None,
            text=RichText.model_validate(
                {"text": str(row[7]), "inline": json.loads(row[8] or "[]")}
            ),
        )

    async def states_for(
        self,
        *,
        exam: str,
        subject: str,
        year: int,
        country: str | None = None,
    ) -> dict[str, tuple[str, bool, bool]]:
        """The state of every row already held for one scope.

        One query lets a scrape skip a finished row without a load per source
        item. The error flag says a DEDUPED row failed and must be retried;
        the pending flag says a row still holds refs or blobs, which is the
        crash window between dedupe and capture. Either one means load it.
        """
        result = await self._client.execute(
            "SELECT id, state, error IS NOT NULL, "
            "(media_refs IS NOT NULL AND media_refs != '[]') OR "
            "(media_blobs IS NOT NULL AND media_blobs != '{}') "
            "FROM staging_items WHERE exam = ? AND subject = ? AND year = ? "
            "AND ((country IS NULL AND ? IS NULL) OR country = ?)",
            [exam, subject, year, country, country],
        )
        return {str(row[0]): (str(row[1]), bool(row[2]), bool(row[3])) for row in result.rows}

    async def load(self, item_id: str) -> StagingItem | None:
        """Read one staging row."""
        result = await self._client.execute(
            f"SELECT {_COLUMNS} FROM staging_items WHERE id = ?",
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
        error: str | None = None,
    ) -> StagingItem:
        """Move a row to a new state. The state machine refuses a wrong move."""
        item = await self.load(item_id)
        if item is None:
            raise KeyError(f"no staging row {item_id!r}")
        if item.state.value != expected:
            raise InvalidTransition(f"row is {item.state.value}, not {expected}")
        resolved = State(target)
        if not can_transition(item.state, resolved):
            raise InvalidTransition(f"cannot move from {item.state.value} to {resolved.value}")
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
            f"SELECT {_COLUMNS} FROM staging_items WHERE state = ? ORDER BY created_at LIMIT ?",
            [state, limit],
        )
        return tuple(_row_to_item(row) for row in result.rows)

    async def list_by_states(
        self,
        states: Sequence[str],
        *,
        limit: int = 100,
        exam: str | None = None,
        subject: str | None = None,
        year: int | None = None,
        country: str | None = None,
    ) -> tuple[StagingItem, ...]:
        """Read the rows in any of several states, optionally within a scope.

        Processing spans states on purpose: a media step has to pick up a row
        that crashed at ``media_ready`` as well as one that is still
        ``catalogued``, and the count of round trips must not grow with the
        number of states.
        """
        values = tuple(states)
        if not values:
            return ()
        placeholders = ", ".join("?" for _ in values)
        clauses = [f"state IN ({placeholders})"]
        args: list[Any] = list(values)
        for column, value in (("exam", exam), ("subject", subject), ("year", year)):
            if value is not None:
                clauses.append(f"{column} = ?")
                args.append(value)
        if country is not None:
            clauses.append("country = ?")
            args.append(country)
        args.append(limit)
        result = await self._client.execute(
            f"SELECT {_COLUMNS} FROM staging_items "
            f"WHERE {' AND '.join(clauses)} ORDER BY created_at LIMIT ?",
            args,
        )
        return tuple(_row_to_item(row) for row in result.rows)

    async def counts_by_state(self) -> dict[str, int]:
        """How many rows sit in each state. One query, for the status report."""
        result = await self._client.execute(
            "SELECT state, count(*) FROM staging_items GROUP BY state"
        )
        return {str(row[0]): int(row[1]) for row in result.rows}


def _evidence(item: StagingItem) -> dict[str, Any]:
    return {
        "image_descriptions": [d.model_dump(mode="json") for d in item.evidence.image_descriptions],
        "tag": item.evidence.tag.model_dump(mode="json") if item.evidence.tag else None,
        "explanation": (
            item.evidence.explanation.model_dump(mode="json") if item.evidence.explanation else None
        ),
        "answer_verdict": (
            item.evidence.answer_verdict.model_dump(mode="json")
            if item.evidence.answer_verdict
            else None
        ),
        "gate": item.evidence.gate.model_dump(mode="json") if item.evidence.gate else None,
        "verifications": [v.model_dump(mode="json") for v in item.evidence.verifications],
    }


def _row_to_item(row: tuple[Any, ...]) -> StagingItem:
    from utmelab_bank.domain.enums import State
    from utmelab_bank.domain.models import (
        CatalogRef,
        Content,
        Evidence,
        Hashes,
        MediaAsset,
        MediaRef,
        Passage,
        Provenance,
        Scope,
    )

    (
        item_id,
        state,
        exam,
        subject,
        year,
        country,
        source,
        source_item_id,
        source_url,
        payload_hash,
        content_hash,
        bundle_hash,
        content,
        passage,
        catalog,
        media,
        evidence,
        attempts,
        error,
        created_at,
        updated_at,
        section,
        source_version,
        media_refs,
        media_blobs,
    ) = row

    return StagingItem(
        id=item_id,
        provenance=Provenance(
            source=source,
            source_url=source_url,
            source_item_id=source_item_id,
            fetched_at=datetime.fromisoformat(created_at),
            payload_hash=payload_hash,
            source_version=source_version or "1",
            scope=Scope(
                exam=exam,
                subject=subject,
                year=year,
                section=section,
                country=country,
            ),
        ),
        content=Content.model_validate_json(content),
        passage=Passage.model_validate_json(passage) if passage else None,
        media_assets=tuple(MediaAsset.model_validate(asset) for asset in json.loads(media)),
        media_refs=tuple(MediaRef.model_validate(ref) for ref in json.loads(media_refs or "[]")),
        evidence=Evidence.model_validate(json.loads(evidence)),
        catalog=CatalogRef.model_validate_json(catalog) if catalog else None,
        state=State(state),
        hashes=(
            Hashes(
                payload_hash=payload_hash,
                content_hash=content_hash,
                bundle_hash=bundle_hash,
            )
            if content_hash and bundle_hash
            else None
        ),
        attempts=attempts,
        error=error,
        created_at=datetime.fromisoformat(created_at),
        updated_at=datetime.fromisoformat(updated_at),
        media_blobs={k: bytes.fromhex(v) for k, v in json.loads(media_blobs or "{}").items()},
    )


__all__ = ["StagingStore"]
