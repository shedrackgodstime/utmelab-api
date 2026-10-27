"""Return stale placements to the queue.

A tag is stale when the topic or subtopic it names is not in the production
catalog *as the runtime would read it* (exam, subject and country scope). A
catalog reseed changes slugs, and a tag written before the reseed can point at
a row that no longer exists. The review gate would reject such a row, but it
sits in ``catalogued`` looking finished, so the batch skips it.

This clears the tag and goes back to ``deduped``. Content, passage, media and
hashes stay as they are. Dry run by default; pass ``--apply`` to write.

Run it after any catalog reseed, before a tag batch:

    .venv/bin/python scripts/reset_stale_tags.py
    .venv/bin/python scripts/reset_stale_tags.py --apply

"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime

from utmelab_bank.adapters.catalog import ProductionCatalogReader
from utmelab_bank.adapters.database import bank_client, prod_client
from utmelab_bank.adapters.store.staging import StagingStore
from utmelab_bank.config import load_settings
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem

STATES = ("catalogued", "enriched", "verified", "ready")


def _reset(item: StagingItem) -> StagingItem:
    evidence = item.evidence.model_copy(update={"tag": None})
    return item.model_copy(
        update={
            "state": State.DEDUPED,
            "catalog": None,
            "evidence": evidence,
            "error": None,
            "updated_at": datetime.now(UTC),
        }
    )


async def main(apply: bool) -> None:
    settings = load_settings()
    bank = bank_client(settings)
    prod = prod_client(settings)
    store = StagingStore(bank)
    reader = ProductionCatalogReader(prod)
    snapshots: dict[tuple[str, str, str | None], tuple[str, set[str], set[str]]] = {}
    try:
        rows = await store.list_by_states(STATES, limit=10_000)
        stale: list[StagingItem] = []
        for row in rows:
            scope = row.provenance.scope
            key = (scope.exam, scope.subject, scope.country)
            if key not in snapshots:
                snapshot = await reader.snapshot(scope.exam, scope.subject, scope.country)
                snapshots[key] = (
                    snapshot.version,
                    {topic.id for topic in snapshot.topics},
                    {subtopic.id for subtopic in snapshot.subtopics},
                )
            version, topic_ids, subtopic_ids = snapshots[key]
            placement = row.catalog
            if placement is None:
                continue
            if placement.topic_id not in topic_ids or placement.subtopic_id not in subtopic_ids:
                stale.append(row)
            elif placement.catalog_version != version:
                print(
                    f"warn: {row.id} resolves but was stamped "
                    f"{placement.catalog_version[:20]} (now {version[:20]})"
                )

        counts = Counter((row.provenance.scope.exam, row.state.value) for row in stale)
        print(f"rows read: {len(rows)}")
        print(f"stale-tagged rows: {len(stale)}")
        for key, number in sorted(counts.items()):
            print(f"  {key[0]} {key[1]}: {number}")
        if not apply:
            print("\ndry run: nothing written. Re-run with --apply.")
            return

        for row in stale:
            reset = _reset(row)
            assert reset.state is State.DEDUPED
            assert reset.catalog is None
            assert reset.evidence.tag is None
            await store.save(reset)
        print(f"\nreset {len(stale)} rows to deduped")

        after = await store.list_by_states(STATES, limit=10_000)
        print("placements left in non-terminal states:", len(after))
        print(json.dumps({"stale_ids": [row.id for row in stale[:10]]}))
    finally:
        await bank.close()
        await prod.close()


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
