#!/usr/bin/env python3
"""Harvest exam questions from a public source into our Question shape.

What this is for
----------------
`utmelab-api` needs a lot more questions, and the 2025 UTME papers are the ones
students ask for first. This script pulls stem, options and the answer key from
a source and writes rows we can actually import.

What it deliberately does NOT do
--------------------------------
* **It never sets `verified`.** Harvested rows carry no verified key at all —
  the flag is derived at load from the verification log (D62), so everything
  lands unverified. Third-party answer keys contain errors — we proved it
  during the D45 audit, where two "verified" questions had wrong answers *and*
  explanations written to justify them. A key is not a review.
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
import html
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

# The same argument for a passage. A cloze question is not the gap — the gap
# is a pointer into a stimulus we may not hold, and "Fill the gap labelled 9"
# over four options is a coin flip without it. Ten JAMB rows entered the bank
# this way in 2025 (docs/CLOZE_PROBLEM.md); the passage was on the source page
# the whole time, in a `ref` field nothing read.
CLOZE_HINT = re.compile(
    r"\b(fill|complete|supply|choose)[a-z ]{0,12}\b(gap|blank|space|passage)\b",
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
    """Backwards-compatible plain-text cleaning: `clean_inline` then drop marks.

    Kept for callers that need a string (logging, filenames). The harvest
    path itself uses `clean_inline` so markup survives as marks (D61).
    """
    return clean_inline(fragment)["text"]


def unescape_segment(segment: str) -> str:
    """Unescape entities in one tag-free run of text.

    Enumerating entities by hand is a losing game: this source alone uses
    `&rsquo;`, `&deg;`, `&agrave;`, `&ordm;`, `&rarr;`, `&equiv;`, `&epsilon;`
    and the entire upper- and lower-case accented Latin set. A 139-question
    payload shipped with raw entities because the table was incomplete, and
    extending it by hand simply moved the failure. `html.unescape` knows them
    all.

    The double-escape pass stays explicit: `&amp;rsquo;` arrives already
    escaped once, and unescaping in the wrong order leaves `&rsquo;` behind.
    """
    text = segment.replace("&amp;amp;", "\x00AMP\x00")
    text = html.unescape(text)
    return text.replace("\x00AMP\x00", "&")


# Inline tags the source uses for emphasis and scripts, mapped to D60 marks.
# Anything else (`<span>`, `<font>`, classes) is dropped but its text kept.
INLINE_TAGS = {
    "u": "underline",
    "em": "italic",
    "i": "italic",
    "strong": "bold",
    "b": "bold",
    "s": "strike",
    "strike": "strike",
    "sub": "subscript",
    "sup": "superscript",
}

TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)\b([^>]*)>", re.S)
IMG_SRC = re.compile(r'src="([^"]+)"')


def clean_inline(fragment: str) -> dict:
    """One run of prose -> RichText `{"text", "inline"}` (D61).

    Entities are unescaped *per text run* (never before tag-splitting, or
    `&lt;` would become a fake tag), inline tags become marks with Unicode
    scalar offsets, and every other tag dies while its text lives. `<br>`
    becomes a space: stems and options stay single-line (D56) — paragraph
    breaks (`\\n\\n`) belong to passages via `clean_blocks`, never here.
    Offsets are computed on the final text, so the loader's bounds check
    sees exactly what we emit.
    """
    text_parts: list[str] = []
    marks: list[dict] = []
    stack: list[tuple[str, int]] = []  # (kind, start)
    out_len = 0

    def push_text(run: str) -> None:
        nonlocal out_len
        run = unescape_segment(run)
        run = re.sub(r"\s+", " ", run)
        if not run:
            return
        if not text_parts or text_parts[-1].endswith(" "):
            run = run.lstrip(" ")
        if not run:
            return
        text_parts.append(run)
        out_len += len(run)

    def push_space() -> None:
        nonlocal out_len
        if text_parts and not text_parts[-1].endswith(" "):
            text_parts.append(" ")
            out_len += 1

    pos = 0
    for match in TAG_RE.finditer(fragment):
        push_text(fragment[pos:match.start()])
        closing, tag, attrs = match.group(1), match.group(2).lower(), match.group(3)
        if tag == "br":
            push_space()
        elif tag == "img" and not closing:
            src = IMG_SRC.search(attrs)
            url = src.group(1) if src else ""
            if url.startswith("https://") and not AD_ASSET.search(url):
                marks.append({
                    "start": out_len, "len": 0, "kind": "image",
                    "url": url, "position": "above", "alt": None,
                })
        elif tag in INLINE_TAGS and not closing:
            stack.append((INLINE_TAGS[tag], out_len))
        elif closing and tag in INLINE_TAGS:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == INLINE_TAGS[tag]:
                    _, start = stack.pop(i)
                    marks.append({"start": start, "len": out_len - start,
                                  "kind": INLINE_TAGS[tag]})
                    break
        pos = match.end()
    push_text(fragment[pos:])
    # Forgiving close: an unclosed mark runs to the end, never past it.
    for kind, start in stack:
        marks.append({"start": start, "len": out_len - start, "kind": kind})

    text = "".join(text_parts).rstrip(" ")
    dropped = len("".join(text_parts)) - len(text)
    if dropped:
        fixed = []
        for m in marks:
            end = min(m["start"] + m["len"], len(text))
            if end > m["start"]:
                fixed.append({**m, "len": end - m["start"]})
        marks = fixed
    marks.sort(key=lambda m: (m["start"], m["len"]))
    return {"text": text, "inline": marks}


def merge_texts(parts: list[dict], sep: str) -> dict:
    """Join RichText fragments, shifting mark offsets (D61)."""
    texts, marks, pos = [], [], 0
    for part in parts:
        if not part["text"]:
            continue
        if texts:
            texts.append(sep)
            pos += len(sep)
        texts.append(part["text"])
        for m in part["inline"]:
            marks.append({**m, "start": m["start"] + pos})
        pos += len(part["text"])
    marks.sort(key=lambda m: (m["start"], m["len"]))
    return {"text": "".join(texts), "inline": marks}


def clean_blocks(fragments: list[str]) -> dict:
    """Block-level fragments -> one RichText with `\\n\\n` breaks (D61).

    Reserved for passage-shaped content: a passage that is really four
    paragraphs keeps its breaks. Stems and options never come through here —
    they stay single-line via `merge_texts(..., " ")` (D56).
    """
    return merge_texts([clean_inline(f) for f in fragments], "\n\n")



# ── passages ─────────────────────────────────────────────────────────────────
# A question that points at a stimulus we do not hold is a coin flip, not a
# question. On this source the stimulus sits ABOVE the stem — in the page body
# before the `<h1>`, ending in its source attribution. An earlier version of
# this harvester read it into a `ref` field nothing consumed, so ten JAMB rows
# entered the bank as pointers with no passage; `docs/CLOZE_PROBLEM.md` records
# that, and `data/` still carried the damage for years.
#
# So: extract the passage, and when a stem announces a stimulus we did not
# manage to extract, refuse the row rather than import a broken question.
PASSAGE_BANNER = re.compile(
    r"(?i)^(read (?:the )?passage|answer question[s]? (?:below|using)|"
    r"use the information below|use the information|following (?:the )?(?:passage|data|table))"
)
ATTRIBUTION = re.compile(r"(?i)^\[?\s*(adapted from|source\s*:|from\b|quoted from)")
# The page renders the credit as three separate elements — `[`, the citation,
# `]` — so the bracket run has to be closed by hand rather than by one regex.
NAV_NOISE = re.compile(
    r"(?i)^(shop|dash|english language|jamb \d{4}|waec \d{4}|home|login|register|"
    r"download offline app|add to bookmark|ask a question|report an error|share|"
    r"copy link|post your contribution|post contribution|go back|prev question|"
    r"next question|explanation|correct option|get myschool|video explanation)\b"
)
MIN_PASSAGE_CHARS = 200


def visible_lines(html: str) -> list[str]:
    """Readable text of a page fragment, one entry per line, whitespace folded."""
    text = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in html_unescape(text).split("\n")]
    return [line for line in lines if line]


def extract_passage(html: str) -> str | None:
    """The stimulus that precedes this question, or None when there is none.

    Read from the tail: find the attribution line (the stimulus's own credit),
    then walk back to the banner that announced it ("Read the passage..."), and
    take everything between. A fragment that never reaches its banner is not a
    passage — it is the page's navigation, and returning it would attach an ad
    menu to a question.
    """
    stem_at = html.find("<h1")
    if stem_at < 0:
        return None
    lines = [line for line in visible_lines(html[:stem_at]) if not NAV_NOISE.match(line)]
    tail = range(max(0, len(lines) - 12), len(lines))
    citation = next((i for i in tail if ATTRIBUTION.match(lines[i])), None)
    if citation is None:
        return None
    # Keep the credit with the passage: it is part of the provenance, and it
    # ends the run so nothing after it (footer, nav) can leak in.
    end = next(
        (i for i in range(citation + 1, len(lines)) if lines[i].strip().startswith("]")),
        citation,
    )
    start = next(
        (i for i in range(citation, -1, -1) if PASSAGE_BANNER.match(lines[i])), None
    )
    if start is None:
        return None
    body = " ".join(lines[start + 1 : citation]).strip()
    credit = " ".join(lines[citation : end + 1])
    # the credit is rendered as three elements; strip the brackets wherever the
    # whitespace put them, then re-add exactly one pair
    credit = credit.strip().lstrip("[").rstrip("]").strip()
    passage = f"{body} [{credit}]".strip() if body else f"[{credit}]"
    return passage if len(passage) >= MIN_PASSAGE_CHARS else None


def html_unescape(text: str) -> str:
    """`html.unescape`, kept local so the passage reader cannot import the
    module-level helper's entity-ordering assumptions (see `unescape_segment`)."""
    return html.unescape(text)


# A stem that promises a stimulus the row does not carry.
PROMISED_STIMULUS = re.compile(
    r"(?i)\b(passage (?:below|above)|the (?:passage|text|information|data|table) "
    r"(?:below|above)|following (?:the )?passage|read the passage|"
    r"use the information below|according to the (?:passage|text|information))\b"
)

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
        if page % 10 == 0 or not found:
            print(f"    listing: {len(seen)} questions found so far", file=sys.stderr, flush=True)
        time.sleep(delay)
    print(f"    listing complete: {len(seen)} questions available", file=sys.stderr, flush=True)
    return seen


def parse_detail(html: str) -> dict | None:
    """Pull stem, options and the correct option out of one detail page.

    Stems keep D60 marks (underline, scripts) via `clean_inline`; multiple
    `<p>` fragments join with a space so stems stay single-line (D56).
    """
    stem_match = STEM.search(html)
    if stem_match is None:
        return None
    stem = merge_texts(
        [clean_inline(p) for p in STEM_P.findall(stem_match.group(1))], " "
    )

    options: dict[str, dict] = {}
    answer: str | None = None
    for classes, letter, text in ROW.findall(html):
        letter = letter.lower()
        options[letter] = clean_inline(text)
        if CORRECT_MARK in classes:
            answer = letter

    if not stem["text"] or len(options) < 2 or answer is None:
        return None

    return {
        "text": stem,
        "options": [{"id": letter, "text": options[letter]} for letter in sorted(options)],
        "answer": answer,
        "images": question_images(html),
        # The stimulus travels with the row, or the row is refused below.
        "passage": extract_passage(html),
    }


def to_question(parsed: dict, subject: str, year: int, qid: str) -> dict | None:
    if len(parsed["options"]) < 2:
        return None
    if parsed["answer"] not in {o["id"] for o in parsed["options"]}:
        # A key that points outside the option set is a broken row. Refusing it
        # is the whole point: importing it would put a wrong answer in the bank.
        return None

    images = parsed.get("images") or []
    if not images and FIGURE_HINT.search(parsed["text"]["text"]):
        # "In the diagram below…" with no diagram. Refused, not imported.
        return None

    if not parsed.get("passage") and CLOZE_HINT.search(parsed["text"]["text"]):
        # "Fill the gap labelled 6" with no passage. The gap is a pointer into
        # a stimulus we do not hold, so the row is unanswerable as served.
        return None

    # Same argument, wider net: ANY stem that promises a passage, text, table
    # or data block must arrive with one. Before this, `parse_detail` never set
    # "passage", so the check above could never fire — the guard was written and
    # inert, and five English comprehension rows plus one commerce row sit in
    # the bank for exactly that reason.
    if not parsed.get("passage") and PROMISED_STIMULUS.search(parsed["text"]["text"]):
        return None

    def has_image_mark(rt):
        return any(m.get("kind") == "image" for m in rt.get("inline", []))

    # An inline <img> already mapped to a mark must not also ride along as a
    # string — import would anchor it twice.
    image_str = images[0] if images else None
    if image_str and (has_image_mark(parsed["text"])
                      or any(has_image_mark(o["text"]) for o in parsed["options"])):
        image_str = None

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
        # Import converts it to an Image anchor mark (D60).
        "image": image_str,
        # Never verified on arrival — see the module docstring.
        "explanation": None,
        "marks": 2.5,
        "difficulty": 3,
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