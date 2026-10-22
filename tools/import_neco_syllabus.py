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

WAEC PDF Import (authorized edit)
---------------------------------
WAEC publishes official PDF syllabi at https://waecsyllabus.com/files/ssce/*.pdf
These use a two-column layout: CONTENTS (left) and NOTES (right). The CONTENTS
column holds the hierarchy: Section (A/B/C) -> Letter (A, B, C...) -> Numbered
topics (1., 2...) -> Lettered subtopics (a, b, c...) -> Roman sub-subtopics (i, ii...).
The NOTES column holds the detailed guidance for each subtopic.

This tool adds a `--waec-pdf` mode to parse these PDFs locally. It is run
manually; the output is written to data/waec/{subject}.json.

Usage
-----
    # NECO import (existing)
    python3 tools/import_neco_syllabus.py --subject civic-education
    python3 tools/import_neco_syllabus.py --subject english --dry-run

    # WAEC PDF import (new)
    python3 tools/import_neco_syllabus.py --waec-pdf /path/to/BIOLOGY.pdf --dry-run
    python3 tools/import_neco_syllabus.py --waec-pdf /path/to/BIOLOGY.pdf --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

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

# WAEC PDF parsing constants
WAEC_SECTION_RE = re.compile(r"^SECTION\s+([ABC])\s*\((.+)\)", re.I)
WAEC_LETTER_RE = re.compile(r"^([A-Z])\.\s+(.+)$")
WAEC_NUMBER_RE = re.compile(r"^(\d+)\.\s+(.+)$")
WAEC_SUB_LETTER_RE = re.compile(r"^\(([a-z])\)\s*(.+)$")
WAEC_SUB_ROMAN_RE = re.compile(r"^\(([ivx]+)\)\s*(.+)$", re.I)

# Country mapping for WAEC sections
SECTION_COUNTRIES = {
    "A": [],  # empty = all countries
    "B": ["GH"],
    "C": ["NG", "SL", "GM", "LR"],
}

# Continent/exam constants
WAEC_EXAM = "WAEC"
WAEC_COUNTRIES = ["NG", "GH", "SL", "GM", "LR"]

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


# =============================================================================
# WAEC PDF PARSING
# =============================================================================

# Coordinate thresholds for column separation
LEFT_COL_MAX_X = 200.0  # CONTENTS column ends around x=170
RIGHT_COL_MIN_X = 230.0  # NOTES column starts around x=240

# X-position thresholds for structure detection
X_SECTION_LETTER_TOPIC = 100.0    # Section headers, letter headers, numbered topics start here
X_SUBTOPIC_START = 130.0          # (a), (b) subtopics start here
X_CONTINUATION = 160.0            # Continuation lines are indented further

# Regex patterns for parsing CONTENTS column
WAEC_SECTION_RE = re.compile(r"^SECTION\s+([ABC])\s*\((.+)\)", re.I)
WAEC_LETTER_RE = re.compile(r"^([A-Z])\.\s+(.+)$")
WAEC_NUMBER_RE = re.compile(r"^(\d+)\.\s+(.+)$")
WAEC_SUB_LETTER_RE = re.compile(r"^\(([a-z])\)\s*(.+)$")
WAEC_SUB_ROMAN_RE = re.compile(r"^\(([ivx]+)\)\s*(.+)$", re.I)

# Right column section header detection
WAEC_RIGHT_SECTION_RE = re.compile(r"^SECTION\s+([ABC])\s*$", re.I)
WAEC_RIGHT_SECTION_DESC_RE = re.compile(r"^\(For\s+(.+)\)$", re.I)

# Country mapping for WAEC sections
SECTION_COUNTRIES = {
    "A": [],  # empty = all countries
    "B": ["GH"],
    "C": ["NG", "SL", "GM", "LR"],
}

# Continent/exam constants
WAEC_EXAM = "WAEC"
WAEC_COUNTRIES = ["NG", "GH", "SL", "GM", "LR"]


def extract_page_columns(page: "pypdf.Page") -> tuple[list[tuple[float, float, str]], list[tuple[float, float, str]]]:
    """Extract left (CONTENTS) and right (NOTES) column text with coordinates.

    Returns: (left_chunks, right_chunks)
    left_chunks = list of (x, y, text)
    right_chunks = list of (x, y, text)
    """
    chunks = []

    def visitor(text: str, cm, tm, font_dict, font_size):
        if not text or not text.strip():
            return
        x = tm[4] if tm else 0
        y = tm[5] if tm else 0
        chunks.append((x, y, text.strip()))

    page.extract_text(visitor_text=visitor)

    left_chunks = [(x, y, t) for x, y, t in chunks if x < LEFT_COL_MAX_X]
    right_chunks = [(x, y, t) for x, y, t in chunks if x >= RIGHT_COL_MIN_X]

    # Sort by y descending (top to bottom in PDF coordinates)
    left_chunks.sort(key=lambda c: -c[1])
    right_chunks.sort(key=lambda c: -c[1])

    return left_chunks, right_chunks


def merge_left_lines(chunks: list[tuple[float, float, str]], y_tolerance: float = 5.0) -> list[tuple[float, float, str]]:
    """Merge chunks on the same line (similar y) into single lines, keeping x of first chunk."""
    if not chunks:
        return []
    merged = []
    current_x, current_y, current_text = chunks[0]
    for x, y, text in chunks[1:]:
        if abs(y - current_y) <= y_tolerance:
            # Same line, append with space
            current_text += " " + text
        else:
            merged.append((current_x, current_y, current_text))
            current_x, current_y, current_text = x, y, text
    merged.append((current_x, current_y, current_text))
    return merged


def merge_right_lines(chunks: list[tuple[float, float, str]], y_tolerance: float = 5.0) -> list[tuple[float, float, str]]:
    """Merge right column chunks on the same line."""
    if not chunks:
        return []
    chunks = sorted(chunks, key=lambda c: -c[1])
    merged = []
    current_x, current_y, current_text = chunks[0]
    for x, y, text in chunks[1:]:
        if abs(y - current_y) <= y_tolerance:
            current_text += " " + text
        else:
            merged.append((current_x, current_y, current_text))
            current_x, current_y, current_text = x, y, text
    merged.append((current_x, current_y, current_text))
    return merged


def detect_section_from_right(right_lines: list[tuple[float, float, str]], current_section: str | None) -> str | None:
    """Detect section header from right column lines. Returns new section letter or None."""
    for x, y, line in right_lines:
        line = line.strip()
        m = WAEC_RIGHT_SECTION_RE.match(line)
        if m:
            return m.group(1).upper()
        # Also check for "(For all candidates)" style lines that confirm section
        m = WAEC_RIGHT_SECTION_DESC_RE.match(line)
        if m and current_section is not None:
            # This confirms the current section, but doesn't change it
            pass
    return None


class WaecEntry:
    """A node in the WAEC syllabus tree."""
    def __init__(self, kind: str, name: str, level: int, countries: list[str] | None = None):
        self.kind = kind  # "section", "letter", "topic", "subtopic", "subsubtopic"
        self.name = name
        self.level = level  # 0=section, 1=letter, 2=topic, 3=subtopic, 4=subsubtopic
        self.countries = countries or []
        self.children: list[WaecEntry] = []
        self.notes: list[str] = []

    def __repr__(self):
        indent = "  " * self.level
        return f"{indent}{self.kind}: {self.name} ({self.countries})"


def parse_left_column(lines: list[tuple[float, float, str]], section_countries: list[str], section_label: str) -> dict[str, WaecEntry]:
    """Parse the left column (CONTENTS) into a tree of WaecEntry objects.

    lines: list of (x, y, text) sorted by y descending
    section_countries: country scope for this section
    section_label: the section letter ("A", "B", or "C")
    """
    sections: dict[str, WaecEntry] = {}
    current_section: WaecEntry | None = None
    current_letter: WaecEntry | None = None
    current_topic: WaecEntry | None = None
    current_subtopic: WaecEntry | None = None

    for x, y, line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip preamble/header lines that aren't syllabus structure
        if line in ("DETAILED SYLLABUS", "CONTENTS NOTES", "CONTENTS", "NOTES"):
            continue
        if line.startswith("PREAMBLE") or line.startswith("AIMS AND OBJECTIVES") or line.startswith("SCHEME OF EXAMINATION"):
            continue
        if line.startswith("PAPER 1:") or line.startswith("PAPER 2:") or line.startswith("PAPER 3:"):
            continue

        # A. Concept of Living - letter header at left margin
        if x < X_SECTION_LETTER_TOPIC:
            m = WAEC_LETTER_RE.match(line)
            if m:
                letter = m.group(1)
                name = m.group(2).strip()
                if current_section is None:
                    # Create the section entry for this section (A, B, or C)
                    current_section = WaecEntry("section", f"Section {section_label}", 0, section_countries)
                    sections[section_label] = current_section
                current_letter = WaecEntry("letter", name, 1, section_countries)
                current_section.children.append(current_letter)
                current_topic = current_subtopic = None
                continue

            # 1. Classification - numbered topic at left margin
            m = WAEC_NUMBER_RE.match(line)
            if m and current_section is not None:
                num = m.group(1)
                name = m.group(2).strip()
                parent = current_letter or current_section
                current_topic = WaecEntry("topic", f"{num}. {name}", 2, section_countries)
                parent.children.append(current_topic)
                current_subtopic = None
                continue

        # (a) Living and non-living things - subtopic start
        # Subtopics can appear at various x positions, check for pattern
        m = WAEC_SUB_LETTER_RE.match(line)
        if m and current_topic is not None:
            letter = m.group(1)
            name = m.group(2).strip()
            current_subtopic = WaecEntry("subtopic", name, 3, current_topic.countries)
            current_topic.children.append(current_subtopic)
            continue

        # (i) ... - roman sub-subtopic
        m = WAEC_SUB_ROMAN_RE.match(line)
        if m and current_subtopic is not None:
            roman = m.group(1)
            name = m.group(2).strip()
            current_subtopic.name += f"; ({roman}) {name}"
            continue

        # Continuation lines - append to current subtopic if we have one
        # Heuristic: if line doesn't match any pattern and we have a subtopic, it's a continuation
        if current_subtopic is not None:
            # Check if this line looks like a continuation (not a new structural element)
            is_new_structure = (
                WAEC_LETTER_RE.match(line) or
                WAEC_NUMBER_RE.match(line) or
                WAEC_SUB_LETTER_RE.match(line) or
                WAEC_SUB_ROMAN_RE.match(line)
            )
            if not is_new_structure:
                current_subtopic.name += " " + line
                continue

    return sections


def flatten_to_topics(sections: dict[str, WaecEntry]) -> list[dict]:
    """Convert the section tree to the flat topic list format expected by build_waec."""
    result = []
    for sec in sections.values():
        for letter in sec.children:
            for topic in letter.children:
                topic_dict = {
                    "name": topic.name,
                    "contents": [sub.name for sub in topic.children],
                    "objectives": [],  # WAEC has no separate learning objectives per D50
                    "countries": normalize_countries(topic.countries),
                }
                result.append(topic_dict)
    return result


def parse_waec_pdf(pdf_path: Path) -> list[dict]:
    """Parse a WAEC syllabus PDF into a structured topic list.

    Returns a list of topic dicts, each with name, contents (subtopics),
    objectives, and countries.
    """
    if not HAS_PYPDF:
        raise RuntimeError("pypdf not installed. Run: pip install pypdf")

    reader = pypdf.PdfReader(str(pdf_path))

    all_topics: list[dict] = []
    current_section: str | None = None  # "A", "B", or "C"

    for page in reader.pages:
        left, right = extract_page_columns(page)
        # Merge multi-chunk lines
        left = merge_left_lines(left)
        right = merge_right_lines(right)

        # Detect section from right column
        new_section = detect_section_from_right(right, current_section)
        if new_section:
            current_section = new_section

        # If no section detected yet, skip (preamble pages)
        if current_section is None:
            continue

        section_countries = SECTION_COUNTRIES.get(current_section, [])

        # Parse left column for this page's section
        sections = parse_left_column(left, section_countries, current_section)

        # Flatten and add to results
        topics = flatten_to_topics(sections)
        all_topics.extend(topics)

    return all_topics


def normalize_countries(countries: list[str]) -> list[str]:
    """Normalize full-set scope to empty list per our convention."""
    if set(countries) == set(WAEC_COUNTRIES):
        return []
    return sorted(set(countries))


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else list(data.values())[0]


def save(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n")


def build_waec(
    subject_slug: str,
    display_name: str,
    topics: list[dict],
    other_topics: set[str] | None = None,
    other_subtopics: set[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Turn parsed WAEC topics into Topic and Subtopic rows with waec- prefix.

    WAEC topic slugs are prefixed with 'waec-' to avoid collisions with JAMB/NECO.
    """
    topic_rows, subtopic_rows = [], []
    taken_topics: set[str] = set(other_topics or ())
    taken_subs: set[str] = set(other_subtopics or ())

    for index, topic in enumerate(topics, start=1):
        # Topic slug: waec-{subject}-{topic-slug}
        topic_slug = f"waec-{slugify(topic['name'])}"
        topic_slug = unique(topic_slug, taken_topics, subject_slug)
        taken_topics.add(topic_slug)

        countries = normalize_countries(topic.get("countries", []))

        topic_rows.append({
            "slug": topic_slug,
            "subject": subject_slug,
            "exam": WAEC_EXAM,
            "name": topic["name"],
            "order": index,
            "weight": 0,
            "objectives": topic.get("objectives", []),
            "countries": countries,
        })
        for order, content in enumerate(topic.get("contents", []), start=1):
            name = content.rstrip(".")
            sub_slug = f"waec-{slugify(name)}"
            sub_slug = unique(sub_slug, taken_subs, subject_slug)
            taken_subs.add(sub_slug)
            subtopic_rows.append({
                "slug": sub_slug,
                "topic": topic_slug,
                "name": name,
                "order": order,
                "objectives": [],
            })
    return topic_rows, subtopic_rows


def load_waec(path: Path) -> dict:
    """Load existing WAEC data if present."""
    if not path.exists():
        return {"subjects": [], "topics": [], "subtopics": []}
    data = json.loads(path.read_text())
    return data


def save_waec(path: Path, subjects: list[dict], topics: list[dict], subtopics: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "subjects": subjects,
        "topics": topics,
        "subtopics": subtopics,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    # NECO mode (existing)
    parser.add_argument("--subject", help="NECO subject slug, e.g. civic-education")
    parser.add_argument("--display", help="official subject name, e.g. Civic Education")
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
    # WAEC mode (new)
    parser.add_argument("--waec-pdf", help="Path to WAEC syllabus PDF file")
    parser.add_argument("--waec-subject", help="WAEC subject slug (e.g., biology)")
    parser.add_argument("--waec-display", help="WAEC subject display name (e.g., Biology)")
    parser.add_argument("--write", action="store_true", help="Actually write to data/waec/")
    args = parser.parse_args()

    # WAEC mode
    if args.waec_pdf:
        if not args.waec_subject or not args.waec_display:
            print("--waec-subject and --waec-display are required with --waec-pdf", file=sys.stderr)
            return 1
        if not HAS_PYPDF:
            print("pypdf not installed. Run: pip install pypdf", file=sys.stderr)
            return 1

        pdf_path = Path(args.waec_pdf)
        if not pdf_path.exists():
            print(f"PDF not found: {pdf_path}", file=sys.stderr)
            return 1

        print(f"parsing WAEC PDF for {args.waec_display}...", file=sys.stderr)
        topics = parse_waec_pdf(pdf_path)
        print(f"parsed {len(topics)} topics across sections", file=sys.stderr)

        if not topics:
            print("no topics parsed from PDF", file=sys.stderr)
            return 1

        # Load existing WAEC data
        waec_dir = Path("data/waec")
        waec_path = waec_dir / f"{args.waec_subject}.json"
        existing = load_waec(waec_path)

        other_topic_slugs = {t["slug"] for t in existing["topics"] if t["subject"] != args.waec_subject}
        other_subtopic_slugs = {s["slug"] for s in existing["subtopics"]}
        topic_rows, subtopic_rows = build_waec(
            args.waec_subject, args.waec_display, topics, other_topic_slugs, other_subtopic_slugs
        )

        # Show dry-run
        print(f"\nwould write {len(topic_rows)} topics and {len(subtopic_rows)} subtopics")
        for row in topic_rows[:10]:
            sub_count = len([s for s in subtopic_rows if s["topic"] == row["slug"]])
            print(f"  {row['order']:>2}. {row['name']}  ({sub_count} subtopics)  countries={row['countries']}")
        if len(topic_rows) > 10:
            print(f"  ... and {len(topic_rows) - 10} more topics")

        if args.dry_run or not args.write:
            return 0

        # Write WAEC data file
        subjects = existing["subjects"] + [{
            "slug": args.waec_subject,
            "exam": WAEC_EXAM,
            "name": args.waec_display,
            "is_compulsory": False,
            "objective_paper_questions": 50,  # WAEC standard, subject to verification
            "countries": [],
            "syllabus_exam": WAEC_EXAM,
            "syllabus_subject": args.waec_subject,
        }]
        topics_all = existing["topics"] + topic_rows
        subtopics_all = existing["subtopics"] + subtopic_rows
        save_waec(waec_path, subjects, topics_all, subtopics_all)
        print(f"wrote WAEC data to {waec_path}")
        return 0

    # NECO mode (existing)
    if not args.subject or not args.display:
        parser.print_help()
        return 1

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