#!/usr/bin/env python3
"""Recover rows the gate refused for a reason the bank has now fixed.

``rejected`` is a terminal state, which is right for a bad source row: the
bank should not retry it on every run. It is wrong for a row the bank itself
refused because a rule was too broad. Those rows stay down forever even after
the rule is corrected, so they need one of two explicit repairs:

``--regrade`` (preferred when the stored content is sound)
    Run the current gate and dedupe over the stored row, in place. The v6
    figure rule is the case this exists for: the content did not change, the
    rule did.

``--reopen`` (for stale content)
    Set the row back to ``acquired`` and clear the error. The next ``fetch``
    run for that scope adapts the source again and runs the current gate.
    This is what the underline and HTML-comment rows need, because the parser
    fix changes the adapted content, not the rule.

Dry run by default. Pass ``--apply`` to write.

    .venv/bin/python scripts/reopen_rejected.py --regrade
    .venv/bin/python scripts/reopen_rejected.py --regrade --apply

The default codes are the ones the v6 gate no longer refuses, plus the HTML
comment case that the source cleaner now strips. ``review_fail`` and
``novel_leak`` are deliberately excluded: a re-fetch cannot fix a wrong
answer key, and novel content is out of scope for the question bank.

"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utmelab_bank.adapters.gate_service import GateService
from utmelab_bank.config import load_settings
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.runtime import open_store_runtime

DEFAULT_CODES = ("missing_figure", "underline_missing", "html_in_text")

_GATE_RE = re.compile(r"^v\d+:\s*(?P<codes>.+)$")


def codes_for(error: str | None) -> set[str]:
    match = _GATE_RE.match((error or "").strip())
    if not match:
        return set()
    return {code.strip() for code in match.group("codes").split(",") if code.strip()}


def scope_of(row: StagingItem) -> tuple[str, str, int | None]:
    scope = row.provenance.scope
    return scope.exam, scope.subject, scope.year


def backup(rows: list[StagingItem]) -> Path:
    """Keep what the repair is about to change, so a mistake is reversible."""
    folder = Path(__file__).parent.parent / "var"
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"rejected-backup-{stamp}.json"
    path.write_text(
        json.dumps([row.model_dump(mode="json") for row in rows], indent=2)
    )
    return path


async def regrade(runtime, selected: list[StagingItem], *, apply: bool) -> None:
    """Re-run the gate and dedupe over rows whose content is unchanged."""
    gate = GateService()
    if apply and selected:
        print(f"backup: {backup(selected)}")
    passed = 0
    deduped = 0
    refused = 0
    duplicates = 0
    still: list[tuple[str, str]] = []
    for row in selected:
        # `rejected` is terminal, so the row is reopened in memory at the
        # state it held when the gate refused it. Nothing is written until
        # the new verdict is known.
        row = row.model_copy(update={"state": State.ADAPTED, "error": None})
        item = gate.apply(row)
        if item.state is not State.GATED:
            refused += 1
            still.append((row.id, row.error or ""))
            continue
        passed += 1
        item = item.stamp_hashes()
        item = await runtime.dedupe.apply(item)
        if item.state is State.DEDUPED:
            deduped += 1
            if apply:
                await runtime.dedupe.remember(item, origin="bank")
        elif item.state is State.REJECTED:
            duplicates += 1
        if apply:
            await runtime.staging.save(item)

    print(f"\nregraded: {len(selected)}")
    print(f"  gate now passes: {passed}")
    print(f"  deduped:         {deduped}")
    print(f"  duplicates:      {duplicates}")
    print(f"  still refused:   {refused}")
    for item_id, error in still[:20]:
        print(f"    {item_id}: {error[:100]}")
    if not apply:
        print("\ndry run: nothing written. Re-run with --apply.")


async def reopen(runtime, selected: list[StagingItem], *, apply: bool) -> None:
    """Send rows back to acquired so the next fetch re-adapts the source."""
    scopes = Counter(scope_of(row) for row in selected)
    print(f"\nreopen candidates: {len(selected)}")
    if scopes:
        print("\nfetch runs needed after reopening:")
        for (exam, subject, year), number in sorted(scopes.items()):
            print(f"  {exam} {subject} {year}  ({number} rows)")
    if not apply:
        print("\ndry run: nothing written. Re-run with --apply.")
        return

    now = datetime.now(UTC)
    for row in selected:
        reopened = row.model_copy(
            update={"state": State.ACQUIRED, "error": None, "updated_at": now}
        )
        await runtime.staging.save(reopened)
    print(f"\nreopened {len(selected)} rows to acquired")


async def run(args: argparse.Namespace) -> int:
    wanted = {code.strip() for code in args.codes.split(",") if code.strip()}
    settings = load_settings()
    async with open_store_runtime(settings) as runtime:
        rows = await runtime.staging.list_by_states(
            ("rejected",),
            limit=50_000,
            exam=args.exam,
            subject=args.subject,
            year=args.year,
        )
        selected = [row for row in rows if codes_for(row.error) & wanted]

        counts = Counter(
            (code, *scope_of(row))
            for row in selected
            for code in (codes_for(row.error) & wanted)
        )
        print(f"rejected read: {len(rows)}")
        for (code, exam, subject, year), number in sorted(counts.items()):
            print(f"  {code:<22} {exam:<5} {subject:<28} {year}  {number}")

        if args.regrade:
            await regrade(runtime, selected, apply=args.apply)
        else:
            await reopen(runtime, selected, apply=args.apply)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover falsely rejected rows")
    parser.add_argument("--exam", help="Exam filter, e.g. JAMB")
    parser.add_argument("--subject", help="Subject slug filter")
    parser.add_argument("--year", type=int, help="Year filter")
    parser.add_argument(
        "--codes",
        default=",".join(DEFAULT_CODES),
        help=f"Gate codes to recover (default: {','.join(DEFAULT_CODES)})",
    )
    parser.add_argument(
        "--regrade",
        action="store_true",
        help="Re-run gate and dedupe in place instead of reopening for a re-fetch",
    )
    parser.add_argument("--apply", action="store_true", help="Write the changes")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
