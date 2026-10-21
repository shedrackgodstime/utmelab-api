"""The spine. One row walks the whole declared state machine to ready.

Every service has its own contract test, and that is not enough: a contract
test hands a service the state it wants, so it cannot see a join that no
service produces. This is the one test that drives the row through the same
services in the same order the domain declares, and it fails at the first
join the pipeline cannot actually make.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from utmelab_bank.adapters.dedupe_service import DedupeService
from utmelab_bank.adapters.gate_service import GateService
from utmelab_bank.adapters.providers.mock import MockProvider
from utmelab_bank.adapters.providers.tagging import ExplainService, TagService
from utmelab_bank.adapters.ready_service import ReadyService
from utmelab_bank.adapters.review_service import ReviewService
from utmelab_bank.adapters.sources.fixture import FixtureSource
from utmelab_bank.domain.dedupe import Duplicate
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.hashing import bundle_fingerprint, content_fingerprint
from utmelab_bank.domain.models import CatalogSnapshot, Scope, SourceItem, StagingItem
from utmelab_bank.domain.ready import ReadyReport

SCOPE = {"exam": "JAMB", "subject": "Biology", "year": 2024, "section": "A"}


class _EmptyIndex:
    """An index that knows nothing, so nothing looks like a duplicate.

    The real index is covered by its own contract test. The spine only needs
    a dedupe step that finds nothing, so a row reaches the later steps.
    """

    async def remember(
        self,
        *,
        content_hash: str,
        near_duplicate: str,
        origin: str,
        question_id: str,
    ) -> None:
        return None

    async def find(self, *, content_hash: str, near_duplicate: str) -> Duplicate | None:
        return None

    async def exact_match(self, content_hash: str) -> str | None:
        return None

    async def near_matches(self, near_duplicate: str) -> tuple[str, ...]:
        return ()

    async def count(self, origin: str | None = None) -> int:
        return 0


def _write_fixture(directory: Path) -> Path:
    """One clean question: four options, an answer, an explanation, a topic.

    The gate requires a source explanation, four options with the live ids,
    and an answer that names one of them, so the fixture carries all three.
    """
    record = {
        "recorded_at": "2026-10-21T12:00:00Z",
        "items": [
            {
                "source_item_id": "bio-2024-001",
                "source_url": "https://fixture.example/items/bio-2024-001",
                "scope": SCOPE,
                "payload": {
                    "stem": "Which organelle releases most of the energy from glucose?",
                    "options": [
                        {"id": "a", "text": "Nucleus"},
                        {"id": "b", "text": "Mitochondrion"},
                        {"id": "c", "text": "Ribosome"},
                        {"id": "d", "text": "Vacuole"},
                    ],
                    "answer": "b",
                    "marks": 1.0,
                    "explanation": "Mitochondria respire and release energy as ATP.",
                    "topic_id": "t1",
                    "subtopic_id": "s1",
                    "media": [],
                },
            }
        ],
    }
    path = directory / "jamb-biology-2024.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


async def _walk_placeholder() -> None:  # pragma: no cover
    return None


def test_the_spine_reaches_ready(tmp_path: Path, catalog: CatalogSnapshot) -> None:
    _write_fixture(tmp_path)
    source = FixtureSource(tmp_path)
    scope = Scope.model_validate(SCOPE)

    async def walk() -> tuple[SourceItem, StagingItem, ReadyReport]:
        fetched = [item async for item in source.fetch(scope)]
        assert len(fetched) == 1
        raw = fetched[0]

        # adapted: the source row becomes a staging row, hashes stamped
        adapted = source.adapt(raw, catalog)
        assert adapted.state is State.ADAPTED
        assert adapted.hashes is not None
        assert adapted.hashes.content_hash

        # gated: every mechanical rule ran and none refused
        gated = GateService(catalog=catalog).apply(adapted)
        assert gated.state is State.GATED
        assert gated.evidence.gate is not None
        assert gated.evidence.gate.passed

        # deduped: nothing the bank already holds matches
        deduped = await DedupeService(_EmptyIndex()).apply(gated)
        assert deduped.state is State.DEDUPED

        # catalogued: the model placed it, and the placement is in the catalog
        catalogued = await TagService(MockProvider()).tag(deduped, catalog)
        assert catalogued.state is State.CATALOGUED
        assert catalogued.catalog is not None
        assert catalogued.catalog.subtopic_id == "s1"

        # enriched: the explanation exists, so the content hash is re-stamped
        enriched = await ExplainService(MockProvider()).explain(catalogued, catalog)
        assert enriched.state is State.ENRICHED
        assert enriched.evidence.explanation is not None
        assert enriched.hashes is not None

        # verified: the model's check is recorded against the fresh hash
        verified = await ReviewService(MockProvider()).apply(enriched, catalog)
        assert verified.state is State.VERIFIED

        # ready: every condition holds, so the row is promoted
        bundle = ReadyService(catalog=catalog).promote([verified])
        assert bundle.report.satisfied, bundle.report.unmet()
        assert len(bundle.items) == 1
        assert bundle.items[0].state is State.READY
        return raw, bundle.items[0], bundle.report

    raw, ready, report = asyncio.run(walk())

    assert ready.hashes is not None

    # The production predicate the serving side reads: the hash a verification
    # was written against must equal the content hash as it stands.
    assert ready.evidence.verifications
    assert ready.evidence.verifications[-1].content_hash == ready.hashes.content_hash

    # The content hash is production's fingerprint of the content as it stands.
    assert ready.hashes.content_hash == content_fingerprint(
        stem=ready.content.stem,
        options=ready.content.options,
        answer=ready.content.answer,
        explanation=ready.evidence.explanation,
    )

    # The bundle hash is the bank's wider fingerprint, over the parts the
    # production hash ignores.
    assert ready.hashes.bundle_hash == bundle_fingerprint(
        content_hash=ready.hashes.content_hash,
        passage_id=ready.content.passage_id,
        section=ready.content.section,
        media_ids=tuple(asset.asset_id for asset in ready.media_assets),
    )

    # The payload hash is the source payload the row records.
    assert ready.hashes.payload_hash == raw.payload_hash

    # The bank never writes a human row of its own, so the report says none.
    assert report.human_signed == 0
