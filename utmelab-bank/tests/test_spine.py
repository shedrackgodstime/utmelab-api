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

from tests.media_fakes import FakeMediaFetcher, FakeMediaStore
from utmelab_bank.adapters.dedupe_service import DedupeService
from utmelab_bank.adapters.gate_service import GateService
from utmelab_bank.adapters.media import (
    DescribeImageConsensus,
    ImageDescriberService,
    MediaIngestor,
    MediaService,
    PillowMediaValidator,
)
from utmelab_bank.adapters.providers.mock import MockProvider
from utmelab_bank.adapters.providers.tagging import ExplainService, TagService
from utmelab_bank.adapters.ready_service import ReadyService
from utmelab_bank.adapters.review_service import ReviewService
from utmelab_bank.adapters.sources.fixture import FixtureSource
from utmelab_bank.domain.dedupe import Duplicate
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.hashing import bundle_fingerprint, content_fingerprint
from utmelab_bank.domain.models import (
    CatalogSnapshot,
    Producer,
    Scope,
    SourceItem,
    StagingItem,
)
from utmelab_bank.domain.ready import ReadyReport

SCOPE = {"exam": "JAMB", "subject": "Biology", "year": 2024, "section": "A"}
FIGURE_URL = "https://fixture.example/media/figure.png"


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
    """One clean question: four options, an answer, a topic, no explanation.

    It deliberately ships without an explanation. A source that only carries
    the question and a topic is the common case, and the bank's job is to
    author the explanation at the enrich step. This fixture fails at the gate
    unless the gate lets it through to the explainer, which is the join this
    test exists to protect.
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


def _write_figure_fixture(directory: Path) -> Path:
    """One question with a figure: an image inline and the media it names.

    The stem inline points at the source url, which is where a figure lives
    today. The media entry is what the bank tries to own.
    """
    record = {
        "recorded_at": "2026-10-21T12:00:00Z",
        "items": [
            {
                "source_item_id": "bio-2024-002",
                "source_url": "https://fixture.example/items/bio-2024-002",
                "scope": SCOPE,
                "payload": {
                    "stem": "The diagram shows a cell. Which part is labelled X?",
                    "stem_inline": [
                        {
                            "kind": "image",
                            "start": 0,
                            "len": 0,
                            "url": FIGURE_URL,
                            "position": "below",
                        }
                    ],
                    "options": [
                        {"id": "a", "text": "Nucleus"},
                        {"id": "b", "text": "Mitochondrion"},
                        {"id": "c", "text": "Ribosome"},
                        {"id": "d", "text": "Vacuole"},
                    ],
                    "answer": "a",
                    "marks": 1.0,
                    "topic_id": "t1",
                    "subtopic_id": "s1",
                    "media": [{"key": "fig1", "url": FIGURE_URL, "required": True}],
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
        # The source shipped no explanation, and the bank does not ask it to.
        assert adapted.content.source_explanation is None

        # gated: every mechanical rule ran and none refused. The missing
        # explanation is not a refusal, because the explainer has not run yet.
        gated = GateService(catalog=catalog).apply(adapted)
        assert gated.state is State.GATED
        assert gated.evidence.gate is not None
        assert gated.evidence.gate.passed
        assert "explanation_missing" not in {issue.code for issue in gated.evidence.gate.issues}

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


def test_the_spine_carries_a_figure_to_ready(tmp_path: Path, catalog: CatalogSnapshot) -> None:
    """The media path: catalogued -> media_ready -> described -> enriched.

    A figure is the one thing the bank can own that production does not: the
    bytes. This is the join that says the branch runs, the asset is stored,
    the source url is swapped for the bank's own, and the row still reaches
    ready with the two-witness description attached.
    """
    _write_figure_fixture(tmp_path)
    source = FixtureSource(tmp_path)
    scope = Scope.model_validate(SCOPE)

    async def walk() -> tuple[StagingItem, str]:
        raw = [item async for item in source.fetch(scope)][0]
        adapted = source.adapt(raw, catalog)
        assert adapted.media_refs
        assert adapted.content.stem.inline[0].url == FIGURE_URL

        gated = GateService(catalog=catalog).apply(adapted)
        assert gated.state is State.GATED
        deduped = await DedupeService(_EmptyIndex()).apply(gated)
        catalogued = await TagService(MockProvider()).tag(deduped, catalog)
        assert catalogued.state is State.CATALOGUED

        # media: the branch runs because the row brings a ref
        second = MockProvider(producer=Producer(provider="mock", model="mock-v2"))
        media = MediaService(
            MediaIngestor(FakeMediaFetcher(), PillowMediaValidator(), FakeMediaStore()),
            ImageDescriberService(DescribeImageConsensus((MockProvider(), second))),
        )
        described = await media.apply(catalogued)
        assert described.state is State.DESCRIBED
        assert described.evidence.image_descriptions

        enriched = await ExplainService(MockProvider()).explain(described, catalog)
        assert enriched.state is State.ENRICHED
        verified = await ReviewService(MockProvider()).apply(enriched, catalog)
        bundle = ReadyService(catalog=catalog).promote([verified])
        return bundle.items[0], FIGURE_URL

    ready, source_url = asyncio.run(walk())

    assert ready.state is State.READY
    asset = ready.media_assets[0]

    # The bank owns the bytes: the inline points at our url, not the source.
    assert asset.source_url is None
    assert ready.content.stem.inline[0].url == asset.storage_url
    assert ready.content.stem.inline[0].url != source_url

    # The description is on the row, and it is about the asset we stored.
    assert ready.evidence.image_descriptions[0].asset_id == asset.asset_id

    # The hash a verification was written against is the hash as it stands.
    assert ready.hashes is not None
    assert ready.evidence.verifications[-1].content_hash == ready.hashes.content_hash
    assert ready.hashes.bundle_hash == bundle_fingerprint(
        content_hash=ready.hashes.content_hash,
        section="A",
        media_ids=(asset.asset_id,),
    )
