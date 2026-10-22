#!/usr/bin/env python3
"""Import a NECO subject's syllabus from syllabus.ng into our catalog.

Why this exists
---------------
NECO does not publish a machine-readable syllabus. syllabus.ng republishes the
official NECO SSCE syllabi as HTML tables with a consistent structure:

    <table> ... <th>SN</th><th>TOPIC</th><th>OBJECTIVES</th> ... </table>

The OBJECTIVES column contains the examinable contents, numbered (1.1, 1.2,
1.a, (i), (a)...). Those become our subtopics. NECO does not state separate
learning objectives per topic, so topics carry empty objectives - matching
the WAEC model (D50).

Usage
-----
    python3 tools/import_neco_syllabus.py --subject civic-education
    python3 tools/import_neco_syllabus.py --subject english --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://syllabus.ng"
UA = "utmelab-neco-syllabus-importer/1.0 (educational project; contact via repository)"

TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)
TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TH = re.compile(r"<th[^>]*>(.*?)</th>", re.S)
TAG = re.compile(r"<[^>]+>")
BR = re.compile(r"(?i)<br\s*/?>")
GT = re.compile(r"\s*>\s*")
SPLIT_NUM = re.compile(r"^[\d\.]+[a-z]?[\)\.\s]+|^\([ivx]+\)[\s\.]+|^\([a-z]\)[\s\.]+", re.I)
ENTITIES = (
    ("&apos;", "'"),
    ("'", "'"),
    ('"""', '"'),
    ("&", "&"),
    ("<", "<"),
    (">", ">"),
    ("&nbsp;", " "),
    ("&mdash;", "\u2014"),
    ("&ndash;", "\u2013"),
    ("&#8211;", "\u2013"),
    ("&#8212;", "\u2014"),
)

NECO_DIR = Path("data/neco")
SUBJECTS_PATH = NECO_DIR / "subjects.json"
TOPICS_PATH = NECO_DIR / "topics.json"
SUBTOPICS_PATH = NECO_DIR / "subtopics.json"


def slugify(text: str, limit: int = 60) -> str:
    """Lowercase, hyphenated, ASCII - stable enough to be an id forever."""
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > limit:
        text = text[:limit].rstrip("-")
    return text or "topic"


def unescape(text: str) -> str:
    for entity, char in ENTITIES:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", TAG.sub(" ", text)).strip()


def strip_num_prefix(text: str) -> str:
    """Remove leading numbering like 1.1, 1.a, (i), (a)."""
    return SPLIT_NUM.sub("", text).strip()


def fetch(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""
        raise


def parse_table(html: str) -> list[dict]:
    """Extract topics and their subtopics from the syllabus table.

    The table structure:
    1. Optional title row: <td colspan="3">NECO SUBJECT SYLLABUS</td>
    2. Header row: <th>SN</th><th>TOPIC</th><th>OBJECTIVES</th> (or TOPICS)
    3. Data rows: <td>1</td><td>Topic Name</td><td>1.1 item<br />1.2 item</td>
    4. Section rows: <td></td><td>SECTION A</td><td></td> (empty SN)

    Objectives cell contains subtopics separated by <br /> or ">" or newlines,
    each prefixed with a number/letter (1.1, 1.a, (i), (a), etc.).
    """
    topics: list[dict] = []
    for tm in TABLE.finditer(html):
        table_html = tm.group(1)
        rows = TR.findall(table_html)
        if len(rows) < 3:
            continue

        # Find header row (contains TOPIC and OBJECTIVES, SN optional)
        header_idx = -1
        has_sn = False
        ncols = 0
        for i, r in enumerate(rows):
            ths = TH.findall(r)
            tds = TD.findall(r)
            cells = [unescape(c) for c in (ths or tds)]
            if len(cells) >= 2 and any("topic" in c.lower() for c in cells) and any("objective" in c.lower() for c in cells):
                header_idx = i
                ncols = len(cells)
                has_sn = any("sn" == c.lower() for c in cells)
                break
        if header_idx == -1:
            continue

        # If header doesn't declare SN but first data row has numeric/letter first col with 3+ cols, assume SN
        if not has_sn and header_idx + 1 < len(rows):
            first_data = TD.findall(rows[header_idx + 1])
            if len(first_data) >= 3:
                first_cell = unescape(first_data[0]).strip()
                if re.match(r'^[\dIVX]+$', first_cell, re.I) or re.match(r'^[A-Za-z]$', first_cell):
                    has_sn = True

        # Parse data rows after header
        current_topic: str | None = None
        current_subtopics: list[str] = []
        implicit_sn = 0
        for r in rows[header_idx + 1:]:
            tds = TD.findall(r)
            if len(tds) < 2:
                continue
            # Some tables have 4 columns (empty first), use last 3 or 2
            if ncols == 4 and len(tds) >= 4:
                tds = tds[-3:]
            elif ncols == 2 and len(tds) >= 2:
                pass  # already 2 cols: topic, objectives
            elif len(tds) > 3:
                tds = tds[-3:]

            if has_sn:
                if len(tds) < 3:
                    continue
                sn = unescape(tds[0])
                topic_name = unescape(tds[1])
                objectives_raw = tds[2]
            else:
                # No explicit SN column: first col = topic, second = objectives
                sn = ""
                topic_name = unescape(tds[0])
                objectives_raw = tds[1]

            # Section header (empty SN): "SECTION A", "THEME", "SECTION A:ESSAY", etc.
            if (has_sn and not sn) or (not has_sn and not topic_name.strip()):
                # Flush any pending topic
                if current_topic is not None and current_subtopics:
                    topics.append({
                        "name": current_topic,
                        "contents": [c for c in current_subtopics if c],
                        "objectives": [],  # NECO has no separate learning objectives
                    })
                if topic_name:
                    current_topic = topic_name
                current_subtopics = []
                continue

            # Topic row (has SN or implicit SN)
            if sn or not has_sn:
                # Flush previous topic
                if current_topic is not None and current_subtopics:
                    topics.append({
                        "name": current_topic,
                        "contents": [c for c in current_subtopics if c],
                        "objectives": [],
                    })

                if not has_sn:
                    implicit_sn += 1

                current_topic = topic_name
                current_subtopics = []

                # Parse subtopics from objectives cell
                # Split on <br /> or ">" or newlines
                text = BR.sub("\n", objectives_raw)
                text = GT.sub("\n", text)
                text = TAG.sub(" ", text)  # strip any remaining tags
                for line in text.split("\n"):
                    line = unescape(line).strip()
                    if not line:
                        continue
                    # Remove numbering prefix (1.1, 1.a, (i), (a), etc.)
                    clean = strip_num_prefix(line)
                    if clean:
                        current_subtopics.append(clean)

        # Flush last topic
        if current_topic is not None and current_subtopics:
            topics.append({
                "name": current_topic,
                "contents": [c for c in current_subtopics if c],
                "objectives": [],
            })

        if topics:
            return topics

    return []


def strip_num_prefix(text: str) -> str:
    """Remove leading numbering like 1.1, 1.a, (i), (a)."""
    return SPLIT_NUM.sub("", text).strip()


def unique(slug: str, taken: set[str], hint: str = "") -> str:
    """Keep slugs unique across the whole catalog."""
    if slug not in taken:
        return slug
    if hint:
        candidate = f"{slug}-{hint}"
        if candidate not in taken:
            return candidate
    for suffix in range(2, 100):
        candidate = f"{slug}-{suffix}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"cannot make a unique slug from {slug!r}")


def build(
    subject: str,
    catalog_slug: str,
    display: str,
    topics: list[dict],
    other_topics: set[str] | None = None,
    other_subtopics: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Turn parsed topics into Topic and Subtopic rows.

    Slugs must be unique across the whole catalog (including JAMB/WAEC).
    """
    topic_rows, subtopic_rows = [], []
    taken_topics: set[str] = set(other_topics or ())
    taken_subs: set[str] = set(other_subtopics or ())

    for index, topic in enumerate(topics, start=1):
        slug = unique(slugify(topic["name"]), taken_topics, catalog_slug)
        taken_topics.add(slug)
        topic_rows.append({
            "slug": slug,
            "subject": catalog_slug,
            "exam": "NECO",
            "name": topic["name"],
            "order": index,
            "weight": 0,
            "objectives": topic["objectives"],
        })
        for order, content in enumerate(topic["contents"], start=1):
            name = content.rstrip(".")
            sub_slug = unique(slugify(name), taken_subs, catalog_slug)
            taken_subs.add(sub_slug)
            subtopic_rows.append({
                "slug": sub_slug,
                "topic": slug,
                "name": name,
                "order": order,
                "objectives": [],
            })
    return topic_rows, subtopic_rows


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else list(data.values())[0]


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True, help="slug, e.g. civic-education")
    parser.add_argument("--display", required=True, help="official subject name, e.g. Civic Education")
    parser.add_argument(
        "--catalog-slug",
        help="Our slug for this subject, when it differs from the site's.",
    )
    parser.add_argument("--compulsory", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--accept-empty",
        action="store_true",
        help="write the subject row even when the syllabus yields no topics",
    )
    args = parser.parse_args()

    print(f"fetching syllabus for {args.display}...", file=sys.stderr)
    html = fetch(f"{BASE}/neco/{args.subject}/")
    topics = parse_table(html)
    if not topics:
        if not args.accept_empty:
            print("no topics parsed - check the slug or the page layout", file=sys.stderr)
            return 1
        print("no topics parsed - writing subject row only", file=sys.stderr)
    else:
        print(f"parsed {len(topics)} topics", file=sys.stderr)

    subjects = load(SUBJECTS_PATH)
    existing_topics = load(TOPICS_PATH)
    existing_subtopics = load(SUBTOPICS_PATH)

    # If fetch returned no topics (404 or no table), only update subject row; keep existing topics
    if not topics:
        # Update subject row only
        catalog_slug = args.catalog_slug or args.subject
        dropped = [s for s in subjects if s["exam"] == "NECO" and s["slug"] == catalog_slug]
        kept_subjects = [s for s in subjects if not (s["exam"] == "NECO" and s["slug"] == catalog_slug)]
        carried = next(
            (s.get("objective_paper_questions", s.get("full_exam_questions")) for s in dropped),
            None,
        )
        if carried is None:
            carried = 40
        kept_subjects.append({
            "slug": catalog_slug,
            "exam": "NECO",
            "name": args.display,
            "is_compulsory": args.compulsory,
            "objective_paper_questions": carried,
        })
        subjects = sorted(kept_subjects, key=lambda s: (s["exam"], s["slug"]))
        save(SUBJECTS_PATH, subjects)
        print(f"updated subject row for {args.display} (no syllabus page)", file=sys.stderr)
        return 0

    print(f"parsed {len(topics)} topics", file=sys.stderr)

    catalog_slug = args.catalog_slug or args.subject

    # Slugs already in use elsewhere (JAMB + WAEC + other NECO subjects)
    other_topic_slugs = {t["slug"] for t in existing_topics if t["subject"] != catalog_slug}
    other_subtopic_slugs = {s["slug"] for s in existing_subtopics}
    topic_rows, subtopic_rows = build(
        args.subject, catalog_slug, args.display, topics, other_topic_slugs, other_subtopic_slugs
    )

    # Replace this subject's rows (idempotent)
    dropped = [s for s in subjects if s["exam"] == "NECO" and s["slug"] == catalog_slug]
    kept_subjects = [s for s in subjects if not (s["exam"] == "NECO" and s["slug"] == catalog_slug)]
    kept_topics = [t for t in existing_topics if not (t["exam"] == "NECO" and t["subject"] == catalog_slug)]
    replaced = {t["slug"] for t in topic_rows}
    kept_subtopics = [s for s in existing_subtopics if s["topic"] not in replaced]

    # Carry over previously verified objective_paper_questions
    carried = next(
        (s.get("objective_paper_questions", s.get("full_exam_questions")) for s in dropped),
        None,
    )
    if carried is None:
        carried = 40  # NECO standard is 40 for most; English is 60 but unverified

    kept_subjects.append({
        "slug": catalog_slug,
        "exam": "NECO",
        "name": args.display,
        "is_compulsory": args.compulsory,
        "objective_paper_questions": carried,
    })
    subjects = sorted(kept_subjects, key=lambda s: (s["exam"], s["slug"]))
    topics_all = sorted(kept_topics + topic_rows, key=lambda t: (t["subject"], t["order"]))
    subtopics_all = sorted(kept_subtopics + subtopic_rows, key=lambda s: (s["topic"], s["order"]))

    if not topic_rows and not args.accept_empty:
        print(
            f"\nno topics parsed for {args.display} - nothing written. "
            f"Re-run with --accept-empty if a subject with an empty syllabus "
            f"is really what you want.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print(f"\nwould write {len(topic_rows)} topics and {len(subtopic_rows)} subtopics")
        for row in topic_rows[:5]:
            print(f"  {row['order']:>2}. {row['name']}  ({len([s for s in subtopic_rows if s['topic'] == row['slug']])} subtopics)")
        return 0

    save(SUBJECTS_PATH, subjects)
    save(TOPICS_PATH, topics_all)
    save(SUBTOPICS_PATH, subtopics_all)
    print(
        f"wrote {len(topic_rows)} topics, {len(subtopic_rows)} subtopics for {args.display}\n"
        f"subjects={len(subjects)} topics={len(topics_all)} subtopics={len(subtopics_all)}",
        file=sys.stderr,
    )
    time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())