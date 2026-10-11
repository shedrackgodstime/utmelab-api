#!/usr/bin/env python3
"""Harvest every subject's 2025 questions in one pass.

`harvest.py` handles one subject. This drives many, sequentially and politely,
so a full run can sit in the background instead of needing a human to keep
starting it. It writes one file per subject into `data/inbox/` and never
touches `data/questions.json` — merging stays a separate, reviewable step.

It also prints the count each subject *offers*, because that number is not what
you would guess: JAMB Government 2025 alone carries 111 items against a
40-question paper, the surplus being other paper variants and tagged practice
questions. We take what is there and let provenance do the sorting later.

Usage:
    python3 tools/harvest_all.py --year 2025 --delay 2
    python3 tools/harvest_all.py --year 2025 --subjects government,economics
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

START = time.monotonic()


def clock() -> str:
    """Elapsed time, so a quiet run still looks alive."""
    seconds = int(time.monotonic() - START)
    return f"{seconds // 60}m {seconds % 60:02d}s"

spec = importlib.util.spec_from_file_location("harvest", Path(__file__).parent / "harvest.py")
harvest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harvest)

# Slugs as the source spells them.
SUBJECTS = [
    # Already harvested.
    "government",
    "economics",
    "commerce",
    "christian-religious-knowledge-crk",
    "history",
    "geography",
    "agricultural-science",
    "literature-in-english",
    "accounts-principles-of-accounts",
    "mathematics",
    "physics",
    "chemistry",
    "biology",
    "english-language",
    # JAMB's remaining subjects. Every one of these was probed first: each
    # returned 79-150 questions for 2025. Subjects that returned zero
    # (animal-husbandry, civic-education, data-processing, book-keeping,
    # catering-craft, food-and-nutrition, further-mathematics, insurance,
    # marketing, office-practice, technical-drawing, home-management) are NOT
    # here — they are NECO/WAEC subjects, and harvesting them under `jamb`
    # would file the wrong exam's content in the JAMB bank.
    "arabic",
    "computer-studies",
    "fine-arts",
    "french",
    "hausa",
    "home-economics",
    "igbo",
    "islamic-religious-knowledge-irk",
    "physical-education",
    "yoruba",
    # Music offers 38 — under a paper. Left out rather than shipped as the
    # one subject that can never fill a mock.
]


def to_question_rows(path: Path):
    """Re-read one subject's file to count rows carrying a diagram."""
    if not path.exists():
        return []
    return [q for q in json.loads(path.read_text())["questions"] if q.get("image")]


def run(subject: str, year: int, delay: float, limit: int, pages: int, out: Path,
        resume: bool = False) -> tuple[int, int]:
    target = out / f"{subject}-{year}.json"
    harvested: list[dict] = []
    done_ids: set[str] = set()
    skipped = 0

    if resume and target.exists():
        previous = json.loads(target.read_text()).get("questions", [])
        harvested = list(previous)
        # Our ids are `q_claim_{year}_{subject}_{source_id}`, so the source id
        # is the last segment. Comparing our id against the source id never
        # matches, which re-fetched and appended every question — 111 became 222.
        done_ids = {q["id"].rsplit("_", 1)[-1] for q in previous}
        print(f"    resuming: {len(harvested)} already on disk", flush=True)

    def flush() -> None:
        target.write_text(
            json.dumps(
                {"subject": subject, "exam": "JAMB", "year": year, "questions": harvested},
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )

    subject_start = time.monotonic()
    ids = harvest.question_ids(subject, year, pages, delay)
    todo = [q for q in ids[:limit] if q not in done_ids]
    if not todo:
        print(
            f"      nothing to fetch — {len(harvested)} already on disk "
            f"(listing took {int(time.monotonic() - subject_start)}s)",
            flush=True,
        )

    processed = 0
    for qid in todo:
        url = f"{harvest.BASE}/classroom/{subject}/{qid}?exam_type=jamb&exam_year={year}"
        try:
            html = harvest.fetch(url)
        except Exception as error:  # noqa: BLE001 — one bad page must not stop the run
            print(f"    {qid}: fetch failed ({error})", flush=True)
            time.sleep(delay)
            continue
        parsed = harvest.parse_detail(html)
        question = harvest.to_question(parsed, subject, year, qid) if parsed else None
        if question:
            harvested.append(question)
        else:
            skipped += 1

        # Progress tracks *position in the loop*, not successes: counting only
        # successes means a run whose last item is refused never prints its
        # final line, which is exactly when you most want one.
        processed += 1
        if processed % 5 == 0 or processed == len(todo):
            # Flush every 10: connectivity here drops without warning, and a
            # subject that dies at question 60 must not lose the first 59.
            if processed % 10 == 0:
                flush()
            rate = processed / max(time.monotonic() - subject_start, 1e-9)
            print(
                f"      {processed}/{len(todo)} fetched · {clock()} · "
                f"{rate * 60:.0f}/min · {len(harvested)} on disk",
                flush=True,
            )
        time.sleep(delay)

    flush()
    return len(harvested), skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--subjects", help="comma-separated slugs; default: all of them")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=400, help="max questions per subject")
    parser.add_argument("--pages", type=int, default=40)
    parser.add_argument("--out", default="data/inbox")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip questions already on disk and continue where a previous run stopped",
    )
    args = parser.parse_args()

    subjects = (
        [s.strip() for s in args.subjects.split(",") if s.strip()]
        if args.subjects
        else SUBJECTS
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"harvesting {len(subjects)} subjects for {args.year}", flush=True)
    total = skipped_total = 0
    for index, subject in enumerate(subjects, start=1):
        print(f"\n[{index}/{len(subjects)}] {subject}  ({clock()} elapsed)", flush=True)
        try:
            got, skipped = run(
                subject, args.year, args.delay, args.limit, args.pages, out, args.resume
            )
        except Exception as error:  # noqa: BLE001 — a subject failing must not end the run
            print(f"    {subject}: failed ({error})", flush=True)
            continue
        total += got
        skipped_total += skipped
        # Local helper, not part of the harvest module — calling it as
        # `harvest.to_question_rows` raised AttributeError on the first subject.
        with_image = len(to_question_rows(out / f"{subject}-{args.year}.json"))
        if got == 0:
            # An empty file reads as "this subject has no 2025 paper", which is
            # not what an empty file means — it means we asked the wrong door.
            # `principles-of-accounts` returned HTTP 200 with zero questions;
            # the source spells it `accounts-principles-of-accounts`.
            print(
                f"      {subject}: NOTHING FOUND — check the slug against the "
                f"subject list on the source; an empty file would read as "
                f"'no paper exists'",
                flush=True,
            )
        print(
            f"      {subject}: {got} questions on disk, {skipped} refused, "
            f"{with_image} with diagrams · {clock()} · running total: {total}",
            flush=True,
        )

    print(
        f"\nDONE in {clock()}: {total} questions across {len(subjects)} subjects, "
        f"{skipped_total} refused",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())