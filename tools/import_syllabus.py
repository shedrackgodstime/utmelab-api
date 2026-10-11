#!/usr/bin/env python3
"""Import a subject's syllabus from jambsyllabus.com into our catalog.

Why this exists
---------------
We carry five JAMB subjects; the UTME papers span twenty-five. Until a subject
has subject/topic/subtopic rows, a harvested question has nowhere to live and
the syllabus endpoint has an empty tree. Writing those rows by hand for each
subject is the bottleneck, so we read them from a published rendering of the
official JAMB brochure instead.

**Provenance (D16).** Topic names come from JAMB's own areas of concentration,
reproduced here verbatim; JAMB is credited as the source. What we add is the
slug, the ordering, and the split of a topic's *contents* into subtopics.

**Granularity is JAMB's, not ours.** JAMB states objectives once per topic, not
per sub-line. So objectives land on the topic, and subtopics carry none —
inventing per-subtopic objectives would be us writing an exam we do not set.

**Weights are not published for every subject.** Where a syllabus gives no
per-topic weight we store 0, meaning *not published*, never a guess. Fabricated
weights would show up in the API as facts.

Usage
-----
    python3 tools/import_syllabus.py --subject government
    python3 tools/import_syllabus.py --subject economics --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://jambsyllabus.com"
UA = "utmelab-syllabus-importer/1.0 (educational project; contact via repository)"

TOPIC_BLOCK = re.compile(r'<li class="topic"')
NAME = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
CONTENTS = re.compile(
    r'<p class="topic-label"[^>]*>\s*Contents\s*</p>\s*<ul[^>]*>(.*?)</ul>', re.S
)
OBJECTIVES = re.compile(r'<ol class="abc"[^>]*>(.*?)</ol>', re.S)
ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
TAG = re.compile(r"<[^>]+>")

ENTITIES = (
    ("&#39;", "'"),
    ("&#x27;", "'"),
    ("&quot;", '"'),
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&nbsp;", " "),
    ("&mdash;", "—"),
    ("&ndash;", "–"),
)


def slugify(text: str, limit: int = 60) -> str:
    """Lowercase, hyphenated, ASCII — and stable enough to be an id forever."""
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(text) > limit:
        text = text[:limit].rstrip("-")
    return text or "topic"


def unescape(text: str) -> str:
    for entity, char in ENTITIES:
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", TAG.sub(" ", text)).strip()


def fetch(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_topics(html: str) -> list[dict]:
    """Pull topic name, contents and objectives out of one syllabus page.

    The page marks each topic with `<li class="topic">`, its title with an
    `<h3>`, and labels the two lists (`Contents`, then `Objectives`). Splitting
    on the topic marker rather than matching to the next `</li>` matters: the
    topic body itself contains `<li>` elements, so a non-greedy `</li>` match
    would cut every topic off after its first content line.
    """
    starts = [match.start() for match in TOPIC_BLOCK.finditer(html)]
    topics: list[dict] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(html)
        chunk = html[start:end]

        name_match = NAME.search(chunk)
        if name_match is None:
            continue

        contents_block = CONTENTS.search(chunk)
        objectives_block = OBJECTIVES.search(chunk)
        contents = (
            [unescape(item) for item in ITEM.findall(contents_block.group(1))]
            if contents_block
            else []
        )
        objectives = (
            [unescape(item) for item in ITEM.findall(objectives_block.group(1))]
            if objectives_block
            else []
        )

        topics.append(
            {
                "name": unescape(name_match.group(1)),
                "contents": [c for c in contents if c],
                "objectives": [o for o in objectives if o],
            }
        )
    return [t for t in topics if t["contents"]]


def unique(slug: str, taken: set[str]) -> str:
    """Keep slugs unique inside a subject without silently dropping a topic."""
    if slug not in taken:
        return slug
    for suffix in range(2, 100):
        candidate = f"{slug}-{suffix}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"cannot make a unique slug from {slug!r}")


def build(subject: str, display: str, topics: list[dict]) -> tuple[list[dict], list[dict]]:
    """Turn parsed topics into our Topic and Subtopic rows."""
    topic_rows, subtopic_rows = [], []
    taken_topics: set[str] = set()
    taken_subs: set[str] = set()

    for index, topic in enumerate(topics, start=1):
        slug = unique(slugify(topic["name"]), taken_topics)
        taken_topics.add(slug)
        topic_rows.append(
            {
                "slug": slug,
                "subject": subject,
                "exam": "JAMB",
                "name": topic["name"],
                "order": index,
                # JAMB publishes no per-topic weight for this subject: 0 means
                # "not published", and is not the same as "worth nothing".
                "weight": 0,
                "objectives": topic["objectives"],
            }
        )
        for order, content in enumerate(topic["contents"], start=1):
            name = content.rstrip(".")
            sub_slug = unique(slugify(name), taken_subs)
            taken_subs.add(sub_slug)
            subtopic_rows.append(
                {
                    "slug": sub_slug,
                    "topic": slug,
                    "name": name,
                    "order": order,
                    # Objectives belong to the topic (see the module docstring).
                    "objectives": [],
                }
            )
    return topic_rows, subtopic_rows


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else list(data.values())[0]


def save(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True, help="slug, e.g. government")
    parser.add_argument("--display", required=True, help="official subject name, e.g. Government")
    parser.add_argument("--compulsory", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"fetching syllabus for {args.display}…", file=sys.stderr)
    markdown = fetch(f"{BASE}/{args.subject}")
    topics = parse_topics(markdown)
    if not topics:
        print("no topics parsed — check the slug or the page layout", file=sys.stderr)
        return 1
    print(f"parsed {len(topics)} topics", file=sys.stderr)

    topic_rows, subtopic_rows = build(args.subject, args.display, topics)

    subjects_path = Path("data/subjects.json")
    topics_path = Path("data/topics.json")
    subtopics_path = Path("data/subtopics.json")

    subjects = load(subjects_path)
    existing_topics = load(topics_path)
    existing_subtopics = load(subtopics_path)

    # Replace this subject's rows rather than appending, so re-running after a
    # syllabus correction is idempotent instead of duplicating the tree.
    kept_subjects = [s for s in subjects if not (s["exam"] == "JAMB" and s["slug"] == args.subject)]
    kept_topics = [t for t in existing_topics if not (t["exam"] == "JAMB" and t["subject"] == args.subject)]
    # Drop the subtopics of the topics we are about to replace — keyed on the
    # NEW topic slugs, not the kept ones. Keying on `kept_topics` reads as if it
    # deletes the other subjects' subtopics; it does, and it silently did.
    replaced = {t["slug"] for t in topic_rows}
    kept_subtopics = [s for s in existing_subtopics if s["topic"] not in replaced]

    kept_subjects.append(
        {
            "slug": args.subject,
            "exam": "JAMB",
            "name": args.display,
            "is_compulsory": args.compulsory,
            "full_exam_questions": 40,
        }
    )
    subjects = sorted(kept_subjects, key=lambda s: (s["exam"], s["slug"]))
    topics_all = sorted(kept_topics + topic_rows, key=lambda t: (t["subject"], t["order"]))
    subtopics_all = sorted(kept_subtopics + subtopic_rows, key=lambda s: (s["topic"], s["order"]))

    if args.dry_run:
        print(f"\nwould write {len(topic_rows)} topics and {len(subtopic_rows)} subtopics")
        for row in topic_rows[:5]:
            print(f"  {row['order']:>2}. {row['name']}  ({len([s for s in subtopic_rows if s['topic'] == row['slug']])} subtopics)")
        return 0

    save(subjects_path, subjects)
    save(topics_path, topics_all)
    save(subtopics_path, subtopics_all)
    print(
        f"wrote {len(topic_rows)} topics, {len(subtopic_rows)} subtopics for {args.display}\n"
        f"subjects={len(subjects)} topics={len(topics_all)} subtopics={len(subtopics_all)}",
        file=sys.stderr,
    )
    time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())