#!/usr/bin/env python3
"""Harvest exam questions from a public source into our Question shape.

What this is for
----------------
`utmelab-api` needs a lot more questions, and the 2025 UTME papers are the ones
students ask for first. This script pulls stem, options and the answer key from
a source and writes rows we can actually import.

What it deliberately does NOT do
--------------------------------
* **It never sets `verified`.** Everything lands `false`. Third-party answer
  keys contain errors — we proved it during the D45 audit, where two
  "verified" questions had wrong answers *and* explanations written to justify
  them. A key is not a review.
* **It never invents an explanation.** Our `Explanation` (key_point / body /
  trap) is the product; a scraped one would be worse than none. Those get
  written by hand, or by us, later.
* **It never overwrites.** Output goes to `data/inbox/`, which is not loaded by
  the service. Merging is a separate, reviewable step.

Provenance (D48/D49)
--------------------
    past_paper    a paper we can name and vouch for
    claimed_paper a third party attributes this to a named year; unverified
    authored      we wrote it
    imported      hand-entered, origin unknown

Politeness is not optional here
-------------------------------
The source is somebody else's site. This crawls slowly, identifies itself,
respects a single worker, and stops on any non-success status. Run it as a
person would, not as a crawler would.

Usage
-----
    python3 tools/harvest.py --subject government --year 2025 --pages 2
    python3 tools/harvest.py --subject physics   --year 2025 --pages 5 --out data/inbox
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://myschool.ng"
UA = "utmelab-harvester/1.0 (educational project; contact via repository)"

# The listing renders each question as: text, then options a..d, then a link to
# the detail page carrying an id. Options and stem are separate; the stem only
# appears on the detail page, which is also the only place the answer key is
# published — so we fetch every detail page regardless.
DETAIL = re.compile(r"/classroom/[^/\"']+/(\d+)\?exam_type=([a-z]+)&(?:amp;)?exam_year=(\d+)")
OPTION = re.compile(r"^\s*([a-e])\s*$")

# The detail page is a Nuxt-rendered template, so its markup is consistent:
#
#   <h1 ...><p>THE STEM</p></h1>
#   <div class="flex gap-6 items-center rounded-lg px-4 border-1 border py-2
#        justify-between[ bg-[#DFFFEC] !border-[#0C5132]]">
#     <div class="flex items-center gap-6">
#       <span class="uppercase font-medium">b</span>
#       <p class="font-medium">simple majority method</p>
#
# The green background (#DFFFEC) on the row is how the page marks the correct
# option — a signal in the markup rather than in prose, which is far steadier
# than scraping the rendered text. An earlier text-stripping version absorbed
# the entire page footer into option B; structural parsing cannot do that.
# The heading pads the stem with `&nbsp;` paragraphs around it, so a single
# `<p>` capture takes the padding and yields an empty question. Take the whole
# heading and pick the paragraphs that carry text.
STEM = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
STEM_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
ROW = re.compile(
    r'<div class="(flex gap-6 items-center rounded-lg[^"]*)">\s*'
    r'<div class="flex items-center gap-6">\s*'
    r'<span class="uppercase font-medium">([a-e])</span>\s*'
    r'<p class="font-medium">(.*?)</p>',
    re.S,
)
CORRECT_MARK = "DFFFEC"

# A diagram lives in the question body, between the heading and the first
# option. Ads and avatars are <img> tags too — `/storage/serve/` is a campaign
# banner and `/members/cache/` an avatar — so the question body is bounded by
# the markup around it and ads excluded by path.
OPTION_ROW_START = 'class="flex gap-6 items-center rounded-lg'
IMAGE_SRC = re.compile(r'<img[^>]+src="([^"]+)"')
AD_ASSET = re.compile(r"/storage/serve/|no_image_placeholder|/members/cache/|/ads?/|logo", re.I)

# A question that points at a picture we cannot supply is worse than no
# question: the student reads "in the diagram below" and finds nothing. These
# are refused rather than imported broken.
FIGURE_HINT = re.compile(
    r"\b(diagram|figure|graph|illustrat\w*|shown below|sketch|as shown|"
    r"the graph|fig\.|figure below)\b",
    re.I,
)


def question_images(html: str) -> list[str]:
    """Image URLs that belong to the question itself, in document order."""
    start = html.find("<h1")
    if start < 0:
        return []
    stop = html.find(OPTION_ROW_START, start)
    region = html[start : stop if stop > 0 else start + 8000]
    found = []
    for src in IMAGE_SRC.findall(region):
        if AD_ASSET.search(src):
            continue
        if src not in found:
            found.append(src)
    return found


def clean(fragment: str) -> str:
    """Unescape entities and drop any markup a fragment carries."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    for entity, char in (
        ("&#39;", "'"),
        ("&quot;", '"'),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&nbsp;", " "),
    ):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def fetch(url: str, timeout: int = 30) -> str:
    """One polite request: identified user agent, real timeout, no retry storm."""
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise urllib.error.HTTPError(url, response.status, "not ok", None, None)
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def question_ids(subject: str, year: int, pages: int, delay: float) -> list[str]:
    """Walk the listing, collecting detail-page ids. This is the slow, polite half."""
    seen: list[str] = []
    for page in range(1, pages + 1):
        url = f"{BASE}/classroom/{subject}?exam_type=jamb&exam_year={year}&page={page}"
        html = fetch(url)
        found = DETAIL.findall(html)
        if not found:
            break
        for qid, _exam, _year in found:
            if qid not in seen:
                seen.append(qid)
        print(f"  page {page}: {len(found)} links ({len(seen)} unique so far)", file=sys.stderr)
        time.sleep(delay)
    return seen


def parse_detail(html: str) -> dict | None:
    """Pull stem, options and the correct option out of one detail page."""
    stem_match = STEM.search(html)
    if stem_match is None:
        return None
    stem = " ".join(
        part
        for part in (clean(p) for p in STEM_P.findall(stem_match.group(1)))
        if part
    )

    options: dict[str, str] = {}
    answer: str | None = None
    for classes, letter, text in ROW.findall(html):
        letter = letter.lower()
        options[letter] = clean(text)
        if CORRECT_MARK in classes:
            answer = letter

    if not stem or len(options) < 2 or answer is None:
        return None

    return {
        "text": stem,
        "options": [{"id": letter, "text": options[letter]} for letter in sorted(options)],
        "answer": answer,
        "images": question_images(html),
    }


def to_question(parsed: dict, subject: str, year: int, qid: str) -> dict | None:
    if len(parsed["options"]) < 2:
        return None
    if parsed["answer"] not in {o["id"] for o in parsed["options"]}:
        # A key that points outside the option set is a broken row. Refusing it
        # is the whole point: importing it would put a wrong answer in the bank.
        return None

    images = parsed.get("images") or []
    if not images and FIGURE_HINT.search(parsed["text"]):
        # "In the diagram below…" with no diagram. Refused, not imported.
        return None

    return {
        "id": f"q_claim_{year}_{subject}_{qid}",
        "exam": "JAMB",
        "subject": subject,
        "year": year,
        # Attributed to a named paper by a third party, not verified by us (D49).
        "source": "claimed_paper",
        "text": parsed["text"],
        "options": parsed["options"],
        "answer": parsed["answer"],
        "subtopic_id": None,
        "section": None,
        "passage_id": None,
        # An absolute URL on the source's own CDN; we do not mirror binaries.
        "image": images[0] if images else None,
        # Never verified on arrival — see the module docstring.
        "explanation": None,
        "marks": 2.5,
        "difficulty": 3,
        "verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True, help="source slug, e.g. government")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=25, help="max detail pages to fetch")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between requests")
    parser.add_argument("--out", default="data/inbox")
    args = parser.parse_args()

    print(f"listing: {args.subject} {args.year} ({args.pages} pages)", file=sys.stderr)
    ids = question_ids(args.subject, args.year, args.pages, args.delay)
    if not ids:
        print("no question links found — check the slug or the year", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.subject}-{args.year}.json"

    harvested, skipped = [], 0
    for qid in ids[: args.limit]:
        url = f"{BASE}/classroom/{args.subject}/{qid}?exam_type=jamb&exam_year={args.year}"
        try:
            html = fetch(url)
        except Exception as error:  # noqa: BLE001 — one bad page must not stop the run
            print(f"  {qid}: fetch failed ({error})", file=sys.stderr)
            time.sleep(args.delay)
            continue
        parsed = parse_detail(html)
        question = to_question(parsed, args.subject, args.year, qid) if parsed else None
        if question:
            harvested.append(question)
            print(f"  {qid}: ok", file=sys.stderr)
        else:
            skipped += 1
            print(f"  {qid}: skipped (no key, or key outside the options)", file=sys.stderr)
        time.sleep(args.delay)

    payload = {"subject": args.subject, "exam": "JAMB", "year": args.year, "questions": harvested}
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    print(
        f"\n{len(harvested)} harvested, {skipped} skipped -> {out_path}\n"
        f"all of them verified=false and explanation-less, by design",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())