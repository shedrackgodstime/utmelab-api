"""A live contract test: the ready conditions must describe the live bank.

The eight conditions are the bank's definition of done, so they have to
describe the content that actually exists. This builds a bundle out of the
live production rows and reports where each condition stands.

It is skipped unless ``UTMELAB_LIVE=1`` is set, because it needs the network.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import pytest

from utmelab_bank.adapters.database import prod_client
from utmelab_bank.adapters.ready_service import ReadyService
from utmelab_bank.config import load_settings
from utmelab_bank.domain.models import (
    CatalogRef,
    Content,
    Evidence,
    Explanation,
    GateVerdict,
    Hashes,
    Option,
    Producer,
    Provenance,
    RichText,
    Scope,
    StagingItem,
    Verification,
)
from utmelab_bank.domain.enums import VerificationKind, Verdict
from utmelab_bank.domain.ready import ReadyCondition

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("UTMELAB_LIVE") != "1",
        reason="set UTMELAB_LIVE=1 to run live provider smoke tests",
    ),
]


def _rich(raw: dict[str, Any]) -> RichText:
    return RichText.model_validate(
        {"text": raw["text"], "inline": raw.get("inline") or []}
    )


async def test_the_conditions_describe_the_live_bank() -> None:
    settings = load_settings()
    prod = prod_client(settings)
    rows = (
        await prod.execute(
            "SELECT id, exam, subject, year, source, text, inline, options, answer, "
            "subtopic_id, section, passage_id, explanation, marks, difficulty, "
            "content_hash FROM questions"
        )
    ).rows

    now = datetime.now(UTC)
    items: list[StagingItem] = []
    withheld = 0
    for row in rows:
        qid, exam, subject, year, source, text, inline, options, answer = row[:9]
        subtopic_id, section, passage_id, explanation = row[9:13]
        marks, difficulty, content_hash = row[13:16]
        if not exam:
            # The one withheld row. It names no exam, so the bank refuses
            # it at the gate and it never becomes a staging item.
            withheld += 1
            continue
        parsed = json.loads(options)
        raw_explanation = json.loads(explanation) if explanation else None
        content = Content(
            stem=_rich({"text": text, "inline": json.loads(inline or "[]")}),
            options=tuple(
                Option.model_validate(
                    {
                        "id": option["id"],
                        "text": {
                            "text": option["text"]["text"],
                            "inline": option["text"].get("inline") or [],
                        },
                    }
                )
                for option in parsed
            ),
            answer=answer,
            marks=float(marks),
            passage_id=passage_id,
            section=section,
        )
        # The verification production holds, against the hash it covered.
        record = None
        if raw_explanation:
            record = Verification(
                id=f"{qid}:human",
                kind=VerificationKind.HUMAN,
                verdict=Verdict.PASS,
                scope=("answer", "explanation"),
                content_hash=content_hash,
                reviewer="owner",
                created_at=now,
            )
        # The explanation is part of the fingerprint, so the item has to
        # carry it or the recomputed hash will not match the stored one.
        explanation_model = None
        if raw_explanation:
            explanation_model = Explanation(
                key_point=_rich(raw_explanation["key_point"]),
                body=_rich(raw_explanation["body"]),
                trap=(
                    _rich(raw_explanation["trap"])
                    if raw_explanation.get("trap")
                    else None
                ),
                confidence=0.9,
                producer=Producer(provider="live", model="production"),
            )
        evidence = Evidence(
            gate=GateVerdict(passed=True, rules_version="v2"),
            explanation=explanation_model,
            verifications=(record,) if record else (),
        )
        item = StagingItem(
            id=f"live:{qid}",
            provenance=Provenance(
                source="live",
                source_url=f"https://production.invalid/{qid}",
                source_item_id=qid,
                fetched_at=now,
                payload_hash="b" * 64,
                source_version="1",
                scope=Scope(exam=exam, subject=subject, year=year, section=section),
            ),
            content=content,
            evidence=evidence,
            catalog=(
                CatalogRef(
                    exam=exam,
                    subject=subject,
                    year=year,
                    section=section,
                    topic_id="unknown",
                    subtopic_id=subtopic_id or "",
                    catalog_version="live",
                )
                if subtopic_id
                else None
            ),
            state="verified",
            hashes=Hashes(
                payload_hash="b" * 64,
                content_hash=content_hash,
                bundle_hash="d" * 64,
            ),
            created_at=now,
            updated_at=now,
        )
        items.append(item)

    # The passages production holds, so the resolvable condition is judged
    # against what exists rather than against nothing.
    passage_rows = (await prod.execute("SELECT id FROM passages")).rows
    passage_ids = [str(row[0]) for row in passage_rows]

    bundle = ReadyService(known_passage_ids=passage_ids).bundle(items)

    print()
    for report in bundle.report.conditions:
        print(
            f"  {report.condition.value:14s} met={report.met:5d} "
            f"unmet={report.unmet:5d}"
        )
        for reason in report.reasons:
            print(f"        {reason}")
    print(f"  human signed: {bundle.report.human_signed}")
    print(f"  total: {bundle.report.total}, withheld and skipped: {withheld}")
    print()

    # The conditions that can be judged from a row alone.
    by_condition = {
        report.condition: report for report in bundle.report.conditions
    }
    assert by_condition[
        ReadyCondition.COMPLETE
    ].unmet == 0, "every live row has a stem, options and an answer"
    assert by_condition[
        ReadyCondition.IDENTIFIED
    ].unmet == 0, "every live row's hash matches its content"
    assert by_condition[
        ReadyCondition.GATED
    ].unmet == 0
    assert by_condition[
        ReadyCondition.NEW
    ].unmet == 0
    assert by_condition[
        ReadyCondition.RESOLVABLE
    ].unmet == 0, "every live row names a passage that exists"

    # The live bank's only shortfall is the 50 rows that carry no
    # explanation. They were never reviewed, because a review covers the
    # explanation, so the two conditions fail together and for the same
    # reason.
    unexplained = 50
    assert by_condition[ReadyCondition.REVIEWED].unmet == unexplained
    assert by_condition[ReadyCondition.EXPLANATORY].unmet == unexplained
    assert (
        "no check covers the answer and the explanation"
        in by_condition[ReadyCondition.REVIEWED].reasons
    )
    assert (
        "there is no explanation"
        in by_condition[ReadyCondition.EXPLANATORY].reasons
    )
