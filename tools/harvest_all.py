#!/usr/bin/env python3
"""Harvest exam questions from a public source, driven by `config/harvest.json`.

This is the crawl itself. What runs it — a laptop, a VPS timer, a CI job — is
deliberately not decided here: politeness (single worker, 2s spacing, an
identified user agent) is a property of this file, and where it is launched from
should not change how it behaves. See docs for why the crawl belongs on
infrastructure we control rather than on shared CI runners.

Two modes:

    python3 tools/harvest_all.py --year 2025 --resume    # crawl
    python3 tools/harvest_all.py --probe                 # count only, fetch nothing

`--probe` is the cheap one and the one meant for automation: one listing page
walk per subject-year, no question pages at all. It answers "does a paper exist
yet?" — which is what you want running on a schedule to notice the year a new
paper lands — and it costs a fraction of a full crawl.

Subjects come from `config/harvest.json`, never from a list in this file: the
Rust importer reads the same config, and two lists is how subjects drift.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location("harvest", Path(__file__).parent / "harvest.py")
harvest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harvest)

CONFIG = Path(__file__).parent.parent / "config" / "harvest.json"


def load_config() -> dict:
    return json.loads(CONFIG.read_text())


def count_available(subject: str, year: int, pages: int, delay: float) -> int:
    """How many questions the source lists. Listing pages only — no detail fetches."""
    ids: set[str] = set()
    for page in range(1, pages + 1):
        try:
            html = harvest.fetch(
                f"{harvest.BASE}/classroom/{subject}?exam_type=jamb&exam_year={year}&page={page}"
            )
        except Exception:  # noqa: BLE001 — a dead page means "stop counting", not "fail"
            break
        found = harvest.DETAIL.findall(html)
        if not found:
            break
        ids.update(qid for qid, _, _ in found)
        if len(found) < 5:
            break
        time.sleep(delay)
    return len(ids)


def run(subject: str, year: int, delay: float, limit: int, pages: int, out: Path,
        resume: bool = False) -> tuple[int, int]:
    target = out / f"{subject}-{year}.json"
    harvested: list[dict] = []
    done_ids: set[str] = set()
    skipped = 0

    if resume and target.exists():
        harvested = list(json.loads(target.read_text()).get("questions", []))
        # Our ids are `q_claim_{year}_{subject}_{source_id}`, so the source id is
        # the last segment. Comparing our id against the source id never matches,
        # which re-fetched and appended every question — 111 became 222.
        done_ids = {q["id"].rsplit("_", 1)[-1] for q in harvested}
        print(f"      resuming: {len(harvested)} already on disk", flush=True)

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
        return len(harvested), skipped

    processed = 0
    for qid in todo:
        url = f"{harvest.BASE}/classroom/{subject}/{qid}?exam_type=jamb&exam_year={year}"
        try:
            html = harvest.fetch(url)
        except Exception as error:  # noqa: BLE001 — one bad page must not stop the run
            print(f"      {qid}: fetch failed ({error})", flush=True)
            time.sleep(delay)
            continue
        parsed = harvest.parse_detail(html)
        question = harvest.to_question(parsed, subject, year, qid) if parsed else None
        if question:
            harvested.append(question)
        else:
            skipped += 1

        # Progress tracks position in the loop, not successes: counting only
        # successes means a run whose last item is refused never prints a final
        # line, which is exactly when you most want one.
        processed += 1
        if processed % 5 == 0 or processed == len(todo):
            # Flush every 10: connectivity drops without warning, and a subject
            # that dies at question 60 must not lose the first 59.
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


START = time.monotonic()


def clock() -> str:
    """Elapsed time, so a quiet run still looks alive."""
    seconds = int(time.monotonic() - START)
    return f"{seconds // 60}m {seconds % 60:02d}s"


def to_question_rows(path: Path):
    """Re-read one subject's file to count rows carrying a diagram."""
    if not path.exists():
        return []
    return [q for q in json.loads(path.read_text())["questions"] if q.get("image")]


def probe(config: dict, years: list[int], pages: int, delay: float,
          only: list[str] | None = None) -> int:
    """Count what exists, fetch nothing. The mode meant for a schedule."""
    print(f"{'subject':<34}" + "".join(f"{y:>8}" for y in years))
    findings = []
    entries = config["subjects"]
    if only:
        entries = [e for e in entries if e["source"] in only]
    for entry in entries:
        row = f"{entry['source']:<34}"
        for year in years:
            found = count_available(entry["source"], year, pages, delay)
            row += f"{found if found else '-':>8}"
            findings.append({"source": entry["source"], "year": year, "available": found})
            time.sleep(delay)
        print(row, flush=True)

    Path("var").mkdir(exist_ok=True)
    Path("var/harvest-probe.json").write_text(json.dumps(findings, indent=2) + "\n")
    have = [f for f in findings if f["available"] > 0]
    print(
        f"\n{len(have)} of {len(findings)} subject-years have a paper. "
        f"Wrote var/harvest-probe.json",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, help="crawl a single year; default: every year in the config")
    parser.add_argument("--subjects", help="comma-separated source slugs; default: all")
    parser.add_argument("--probe", action="store_true", help="count only, fetch no question pages")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=400)
    parser.add_argument("--pages", type=int, default=40)
    parser.add_argument("--out", default="data/inbox")
    parser.add_argument("--resume", action="store_true", help="skip rows already on disk")
    args = parser.parse_args()

    config = load_config()
    years = [args.year] if args.year else config.get("years", [2025])
    subjects = (
        [s.strip() for s in args.subjects.split(",") if s.strip()]
        if args.subjects
        else [e["source"] for e in config["subjects"]]
    )

    if args.probe:
        return probe(config, years, min(args.pages, 30), args.delay, subjects or None)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"harvesting {len(subjects)} subjects for {years}", flush=True)

    total = skipped_total = 0
    for index, subject in enumerate(subjects, start=1):
        print(f"\n[{index}/{len(subjects)}] {subject}  ({clock()} elapsed)", flush=True)
        try:
            got, skipped = run(subject, years[0], args.delay, args.limit, args.pages, out, args.resume)
        except Exception as error:  # noqa: BLE001 — a subject failing must not end the run
            print(f"      {subject}: failed ({error})", flush=True)
            continue
        total += got
        skipped_total += skipped

        if got == 0:
            # An empty file reads as "this subject has no paper", which is not
            # what an empty file means — it means we asked the wrong door.
            print(
                f"      {subject}: NOTHING FOUND — check the source slug against "
                f"config/harvest.json; an empty file would read as 'no paper exists'",
                flush=True,
            )
        with_image = len(to_question_rows(out / f"{subject}-{years[0]}.json"))
        print(
            f"      {subject}: {got} questions on disk, {skipped} refused, "
            f"{with_image} with diagrams · {clock()} · running total: {total}",
            flush=True,
        )

    print(
        f"\nDONE in {clock()}: {total} questions, {skipped_total} refused",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())