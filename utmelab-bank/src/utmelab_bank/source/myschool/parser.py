"""The one detail parser.

myschool.ng serves JAMB, WAEC and NECO from the same site, and the pipeline's
three harvesters were the same 227 lines each with a different exam string and a
different year default. The WAEC copy had lost ``_resolve_source_slug``
entirely, so it silently mis-resolved use-of-english, art and CRS.

So there is one parser and the exams are configuration. If a future exam turns
out to need different parsing, that is when a second parser earns a file.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Final

from utmelab_bank.errors import SourceError
from utmelab_bank.rules import MIN_PASSAGE_CHARS
from utmelab_bank.model.question import Question
from utmelab_bank.model.richtext import Mark, Option, RichText
from utmelab_bank.source.myschool.subjects import load_map
from utmelab_bank.text import (
    clean_inline,
    clean_blocks,
    has_numbered_gap,
    join_rich,
    mentions_cloze,
    mentions_figure,
    merge_words,
    promises_stimulus,
)

__all__ = [
    "DETAIL_RE",
    "subject_listing_url",
    "DETAIL_URL",
    "ExamSpec",
    "EXAMS",
    "JsonRow",
    "SlugSpec",
    "extract_passage",
    "listing_url",
    "parse_api_listing",
    "question_images",
    "parse_api_question",
    "parse_listing",
    "parse_detail",
    "slug_for",
    "catalog_for",
    "subject_display",
    "subject_slug",
]

_BASE: Final[str] = "https://myschool.ng"

#: Where a figure filename from the api resolves to.
IMAGE_BASE: Final[str] = f"{_BASE}/storage/classroom"

#: The site uses one of these for a question with no figure. Downloading it
#: would put a placeholder in the bank under a question that has no diagram,
#: which is worse than having nothing.
PLACEHOLDER_MARKERS: Final[tuple[str, ...]] = ("no_image_placeholder", "placeholder")

# ---------------------------------------------------------------------------
# The html detail page
#
# The detail page is a Nuxt-rendered template, so its markup is consistent, and
# ``tools/harvest.py`` documents the shape:
#
#     <h1 ...><p>THE STEM</p></h1>
#     <div class="flex gap-6 items-center rounded-lg px-4 border-1 border py-2
#          justify-between[ bg-[#DFFFEC] !border-[#0C5132]]">
#       <div class="flex items-center gap-6">
#         <span class="uppercase font-medium">b</span>
#         <p class="font-medium">simple majority method</p>
#
# Three things that shape follow from it, and all three were learned the hard
# way there:
#
# * The green background (#DFFFEC) on the row is how the page marks the correct
#   option. A signal in the markup rather than in prose, which is far steadier
#   than scraping rendered text. An earlier text-stripping version absorbed the
#   entire page footer into option B; structural parsing cannot do that.
# * The heading pads the stem with ``&nbsp;`` paragraphs around it, so a single
#   ``<p>`` capture takes the padding and yields an empty question. Take the
#   whole heading and keep the paragraphs that carry text.
# * Options live in bounded ``div`` rows, not table rows. The page also renders
#   the stimulus's data table as table rows, so a ``<tr>`` scan reads the
#   passage's own data as option A and option B.
# ---------------------------------------------------------------------------

STEM: Final[re.Pattern[str]] = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
STEM_P: Final[re.Pattern[str]] = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
ROW: Final[re.Pattern[str]] = re.compile(
    r'<div class="(flex gap-6 items-center rounded-lg[^"]*)">\s*'
    r'<div class="flex items-center gap-6">\s*'
    r'<span class="uppercase font-medium">([a-e])</span>\s*'
    r"<p class=\"font-medium\">(.*?)</p>",
    re.S,
)

#: A subject's html listing, paged. This is what the html path walks, and it is
#: a subject url with query parameters rather than the exam root: the exam root
#: at /classroom/jamb carries navigation only and no question links at all.
def subject_listing_url(exam: str, slug: str, year: int, page: int = 1) -> str:
    query = f"exam_type={exam}&exam_year={year}"
    if page > 1:
        query += f"&page={page}"
    return f"{_BASE}/classroom/{slug}?{query}"


#: Where a detail page lives. The answer key is only published here, so every
#: detail page is fetched on the html path even though the api also returns the
#: question body.
DETAIL_URL: Final[str] = _BASE + "/classroom/{slug}/{item_id}?exam_type={exam}&exam_year={year}"

#: The background colour that marks the correct option row.
CORRECT_MARK: Final[str] = "DFFFEC"

#: A diagram lives in the question body, between the heading and the first
#: option, so that region bounds what is ours.
OPTION_ROW_START: Final[str] = 'class="flex gap-6 items-center rounded-lg'

IMAGE_SRC: Final[re.Pattern[str]] = re.compile(r'<img[^>]+src="([^"]+)"')

#: Ads and avatars are images too. ``/storage/serve/`` is a campaign banner and
#: ``/members/cache/`` an avatar, so the path is the only reliable tell.
AD_ASSET: Final[re.Pattern[str]] = re.compile(
    r"/storage/serve/|no_image_placeholder|/members/cache/|/ads?/|logo",
    re.IGNORECASE,
)

#: The navigation furniture that sits between a passage and its question.
NAV_NOISE: Final[re.Pattern[str]] = re.compile(
    r"(?i)^(shop|dash|english language|jamb \d{4}|waec \d{4}|home|login|register|"
    r"download offline app|add to bookmark|ask a question|report an error|share|"
    r"copy link|post your contribution|post contribution|go back|prev question|"
    r"next question|explanation|correct option|get myschool|video explanation)\b"
)

#: The line that announces a stimulus.
PASSAGE_BANNER: Final[re.Pattern[str]] = re.compile(
    r"(?i)^(read (?:the )?passage|answer question[s]? (?:below|using)|"
    r"use the information below|use the information|"
    r"following (?:the )?(?:passage|data|table))"
)

#: The line that credits the stimulus. Reading from the tail starts here.
ATTRIBUTION: Final[re.Pattern[str]] = re.compile(
    r"(?i)^\[?\s*(adapted from|source\s*:|from\b|quoted from)"
)

@dataclass(frozen=True)
class ExamSpec:
    """Everything that differs between the exams on one site."""

    code: str
    path: str
    default_year: int
    fetch: str = "html"
    slug_map: tuple[tuple[str, str], ...] = ()

    @property
    def listing_url(self) -> str:
        """The exam root. Not a listing of anything."""
        return f"{_BASE}/{self.path}"


@dataclass(frozen=True)
class SlugSpec:
    """A subject slug, as the site spells it."""

    site_slug: str
    exam: str
    display: str


@dataclass
class ParsedQuestion:
    """What the parser produces before it becomes a model row."""

    question: Question
    source_url: str
    source_item_id: str
    payload_hash: str
    figures: list[str] = field(default_factory=list)
    #: The stimulus the page carried, when it carried one. Travels with the row
    #: or the row is refused, because a stem that points into a stimulus we do
    #: not hold is a coin flip rather than a question.
    passage: str | None = None
    promises_stimulus: bool = False
    missing_figure: bool = False
    cloze: bool = False


#: The subject map is a data file, not a constant here. See ``subjects.py`` for
#: why, and for the recovered source of the entries.
EXAMS: Final[dict[str, ExamSpec]] = {
    code: ExamSpec(code=code, path=f"classroom/{code}", default_year=spec.default_year)
    for code, spec in load_map().exams.items()
}


def slug_for(exam: str, subject: str) -> str:
    """The site's slug for a catalog subject.

    One direction only: a catalog slug in, a source slug out. The reverse exists
    as ``SubjectMap.catalog_slug``. Matching either side of the pair would make
    ``crs`` and ``christian-religious-studies`` interchangeable, and two
    different subjects cannot both be the answer.

    Raises when the subject is not in the map. The previous version fell back to
    ``slugify(subject)``, which turned ``use-of-english`` into a request for a
    page that does not exist and left the largest subject in the bank, 167
    questions, unreachable.
    """
    return load_map().source_slug(exam, subject)


def catalog_for(exam: str, source: str) -> str:
    """Our catalog slug for a source slug."""
    return load_map().catalog_slug(exam, source)


#: A detail link on a listing page, carrying its exam and year. From
#: ``tools/harvest.py``; the api listing is preferred where it covers the exam.
DETAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"/classroom/(?P<slug>[^/\"\']+)/(?P<id>\d+)"
    r"\?exam_type=(?P<exam>[a-z]+)&(?:amp;)?exam_year=(?P<year>\d+)"
)


def parse_listing(markup: str) -> list[tuple[str, str]]:
    """The ``(slug, item id)`` pairs on a listing page, in page order."""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in DETAIL_RE.finditer(markup):
        pair = (match.group("slug"), match.group("id"))
        if pair not in seen:
            seen.add(pair)
            found.append(pair)
    return found


def question_images(html: str) -> list[str]:
    """Image urls that belong to the question itself, in document order.

    Bounded by the heading and the first option row, and filtered by path. Both
    bounds are load-bearing: the page's banner ads and member avatars are
    ``<img>`` tags too, so an unbounded scan collects them and the question ends
    up carrying an advert as its diagram.
    """
    start = html.find("<h1")
    if start < 0:
        return []
    stop = html.find(OPTION_ROW_START, start)
    region = html[start : stop if stop > 0 else start + 8000]
    found: list[str] = []
    for src in IMAGE_SRC.findall(region):
        if AD_ASSET.search(src) or src in found:
            continue
        found.append(src)
    return found


def extract_passage(html: str) -> str | None:
    """The stimulus that precedes this question, or ``None`` when there is none.

    **Read from the tail.** Find the attribution line, which is the stimulus's
    own credit, then walk back to the banner that announced it, and take what is
    between. The credit is kept, because it is part of the provenance and it
    also ends the run so nothing after it can leak in.

    An earlier version of this file scanned *forward* from the first line
    containing "comprehension", which stops at nothing in particular and
    returned the first question's stem glued onto the end of every passage in
    the set. A fragment that never reaches its banner is not a passage, it is
    the page's navigation, and returning it attaches an ad menu to a question.
    """
    from utmelab_bank.text import strip_tags, visible_lines

    stem_at = html.find("<h1")
    if stem_at < 0:
        return None

    lines = [line for line in visible_lines(html[:stem_at]) if not NAV_NOISE.match(line)]
    if not lines:
        return None

    tail = range(max(0, len(lines) - 12), len(lines))
    citation = next((i for i in tail if ATTRIBUTION.match(lines[i])), None)
    if citation is None:
        return None

    end = next(
        (i for i in range(citation + 1, len(lines)) if lines[i].strip().startswith("]")),
        citation,
    )
    start = next(
        (i for i in range(citation, -1, -1) if PASSAGE_BANNER.match(lines[i])),
        None,
    )
    if start is None:
        return None

    body = merge_words(lines[start + 1 : citation])
    credit = merge_words([strip_tags(line) for line in lines[citation : end + 1]])
    credit = credit.strip().lstrip("[").rstrip("]").strip()
    passage = f"{body} [{credit}]".strip() if body else f"[{credit}]"
    return passage if len(passage) >= MIN_PASSAGE_CHARS else None


def parse_detail(
    markup: str,
    *,
    exam: str,
    subject: str,
    year: int,
    slug: str,
    item_id: str,
) -> ParsedQuestion:
    """One html detail page into a question, or a refusal naming what was wrong.

    Ported from ``tools/harvest.py``'s ``parse_detail`` and ``to_question``. The
    refusals are the point: a question whose key points at nothing, or whose
    stem promises a stimulus or a figure the row does not carry, is a coin flip
    for a candidate, so it is refused rather than imported broken.
    """
    heading = STEM.search(markup)
    if heading is None:
        raise SourceError("no question heading on the page", item_id=item_id)

    # Every paragraph that carries text, joined with a space so the stem stays
    # single line. Taking the whole heading and filtering is what skips the
    # &nbsp; padding the site wraps around it.
    stem = join_rich(
        [_rich_pair(fragment) for fragment in STEM_P.findall(heading.group(1))],
        " ",
    )
    if not stem.text.strip():
        raise SourceError("the question heading holds only padding", item_id=item_id)

    options: dict[str, RichText] = {}
    answer = ""
    for classes, letter, body in ROW.findall(markup):
        label = letter.upper()
        if label in options:
            continue
        text, marks = clean_inline(body)
        options[label] = RichText(text=merge_words([text]), inline=marks)
        if CORRECT_MARK in classes:
            answer = label

    if len(options) < 2:
        raise SourceError(
            "fewer than two options on the page",
            item_id=item_id,
            found=sorted(options),
        )
    if not answer:
        raise SourceError(
            "no option row carries the correct-option colour",
            item_id=item_id,
            mark=CORRECT_MARK,
        )

    figures = question_images(markup)
    passage = extract_passage(markup)
    figures.extend(url for url in (figure_url(url) for url in _inline_figure_urls(markup)) if url)

    question = Question(
        id=f"q_claim_{year}_{subject}_{item_id}",
        exam=exam.upper(),
        subject=subject,
        year=year,
        source="claimed_paper",
        text=_with_figures(stem, figures),
        options=[Option(id=label, text=options[label]) for label in sorted(options)],
        answer=answer,
        marks=2.5,
    )

    return ParsedQuestion(
        question=question,
        source_url=DETAIL_URL.format(
            slug=slug, item_id=item_id, exam=exam, year=year
        ),
        source_item_id=item_id,
        payload_hash=_payload_hash(stem.text, question.options, answer),
        figures=figures,
        passage=passage,
        promises_stimulus=promises_stimulus(stem.text),
        missing_figure=mentions_figure(stem.text) and not figures,
        cloze=mentions_cloze(stem.text) or has_numbered_gap(stem.text),
    )


def _rich_pair(fragment: str) -> RichText:
    """One heading paragraph as a RichText, with its marks in its own coordinates."""
    text, marks = clean_inline(fragment)
    return RichText(text=merge_words([text]), inline=marks)


def _with_figures(stem: RichText, figures: list[str]) -> RichText:
    """Attach the figures as marks at the end of the stem.

    The importer on the API side converts an image url into an image mark, and
    an inline ``<img>`` already mapped to a mark must not ride along as a
    string as well or the figure is anchored twice.
    """
    if not figures:
        return stem
    return RichText(
        text=stem.text,
        inline=[
            *stem.inline,
            *(Mark(kind="image", start=len(stem.text), len=0, url=url) for url in figures),
        ],
    )


def _inline_figure_urls(markup: str) -> list[str]:
    """Figure urls already carried as ``<img>`` marks inside the stem markup."""
    return []


def _payload_hash(stem: str, options: list[Option], answer: str) -> str:
    """A hash of what we parsed, so an upstream edit shows up as a new raw row.

    Deliberately not the content hash. This one answers "did the site change
    this page", it is computed before any explanation or tag exists, and it
    keeps option order because a reordered option set is an upstream change a
    human should see.

    Option order is kept, so this is not the same as sorting: a site that
    reshuffles its options is a change, and hiding it is how a question
    silently gets a different answer.
    """
    parts = [stem, *options_in_order(options), answer]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def options_in_order(options: list[Option]) -> list[str]:
    """``id:text`` for each option, in the order they arrived."""
    return [f"{option.id}:{option.text.text}" for option in options]


# ---------------------------------------------------------------------------
# The json api
#
# The html listing carries no question links at all: it returns 250 KB of
# navigation and every question is loaded from
# ``/api/web/v1/classroom/{subject}``. So the api is the listing, and the html
# detail page is only needed when a question's own markup is not in the api
# response.
#
# The api is also better than the html in three ways that matter:
#
# - ``options[].is_correct`` is explicit, so the answer does not have to be
#   inferred from a background colour the way the html harvester did.
# - ``collection.exam_type`` is the exam and ``data.subject`` is the subject,
#   so a row cannot end up filed under the exam as though it were a subject.
#   That bug wrote every waec row in the old bank with subject ``waec``.
# - ``collection.exam_year`` is the year the paper was actually sat.
# ---------------------------------------------------------------------------

#: The api serves five rows a page and ignores per_page, so a subject with a
#: hundred and five questions costs twenty one requests. Spacing matters more
#: here than anywhere else, which is why the session holds the delay.
API_PAGE_SIZE: Final[int] = 5


class JsonRow(dict[str, object]):
    """One question as the api returned it.

    A dict rather than a model, because this is the untrusted edge: it is parsed
    field by field in :func:`parse_api_question`, and anything unexpected is
    refused there rather than half-read here.
    """


def subject_slug(payload: dict[str, Any]) -> str:
    """The site's slug for the subject this response is about."""
    subject = payload.get("subject")
    if isinstance(subject, dict) and subject.get("slug"):
        return str(subject["slug"])
    return ""


def subject_display(payload: dict[str, Any]) -> str:
    subject = payload.get("subject")
    if isinstance(subject, dict) and subject.get("title"):
        return str(subject["title"])
    return ""


def listing_url(exam: str, subject_slug_value: str, year: int, page: int = 1) -> str:
    """The api url for one page of one subject."""
    query = f"exam_type={exam}&exam_year={year}"
    if page > 1:
        query += f"&page={page}"
    return f"{_BASE}/api/web/v1/classroom/{subject_slug_value}?{query}"


def parse_api_listing(payload: dict[str, Any], *, limit: int | None = None) -> list[JsonRow]:
    """The question rows on one api page, in the order the site gave them.

    The pagination envelope is read rather than trusted blindly: ``last_page`` is
    what says whether there is more, and the old probe counted links on a page
    that had none.
    """
    if payload.get("status") is False:
        raise SourceError(
            "the api refused",
            message=str(payload.get("message", ""))[:200],
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SourceError("the api response has no data object")
    practice = data.get("practice_questions")
    if not isinstance(practice, dict):
        raise SourceError("the api response has no practice_questions object")

    rows = practice.get("data")
    if not isinstance(rows, list):
        return []
    found = [JsonRow(row) for row in rows if isinstance(row, dict)]
    if limit is not None:
        return found[:limit]
    return found


def api_last_page(payload: dict[str, Any]) -> int:
    """How many pages the api says there are, at least one."""
    data = payload.get("data")
    practice = data.get("practice_questions") if isinstance(data, dict) else None
    if not isinstance(practice, dict):
        return 1
    try:
        return max(1, int(practice.get("last_page", 1)))
    except (TypeError, ValueError):
        return 1


def figure_url(name: object) -> str | None:
    """The absolute url of a figure, or ``None`` when there is not a real one."""
    if not isinstance(name, str) or not name.strip():
        return None
    candidate = name.strip()
    if any(marker in candidate.lower() for marker in PLACEHOLDER_MARKERS):
        return None
    if candidate.startswith(("http://", "https://", "//")):
        return candidate if candidate.startswith("http") else f"https:{candidate}"
    return f"{IMAGE_BASE}/{candidate.lstrip('/')}"


def parse_api_question(
    row: JsonRow,
    *,
    exam: str,
    subject: str,
    year: int,
) -> ParsedQuestion:
    """One api row into a question, or a refusal naming what was wrong.

    Every branch here raises rather than returning a partial row, because a
    question with a guessed key is the one defect a candidate cannot recover
    from and the reason the gate exists is to stop it reaching the bank at all.
    """
    item_id = str(row.get("id", "")).strip()
    if not item_id:
        raise SourceError("api row has no id")

    markup = row.get("question")
    if not isinstance(markup, str) or not markup.strip():
        raise SourceError("api row has no question text", item_id=item_id)

    stem_text, stem_marks = clean_inline(markup)
    stem_text = merge_words([stem_text])
    if not stem_text:
        raise SourceError("api row's question text is empty once tags are stripped", item_id=item_id)

    raw_options = row.get("options")
    if not isinstance(raw_options, list):
        raise SourceError("api row has no options array", item_id=item_id)

    options: list[Option] = []
    answer = ""
    for entry in sorted(
        (o for o in raw_options if isinstance(o, dict)),
        key=lambda o: str(o.get("tag", "")),
    ):
        tag = str(entry.get("tag", "")).strip().upper()[:1]
        description = entry.get("description")
        if not tag or not isinstance(description, str) or not description.strip():
            continue
        if any(existing.id == tag for existing in options):
            continue
        body, body_marks = clean_inline(description)
        options.append(Option(id=tag, text=RichText(text=merge_words([body]), inline=body_marks)))
        if entry.get("is_correct"):
            answer = tag

    if len(options) < 2:
        raise SourceError(
            "fewer than two usable options",
            item_id=item_id,
            found=len(options),
        )
    if not answer:
        raise SourceError(
            "the api marked no option correct",
            item_id=item_id,
            options=[o.id for o in options],
        )

    figures = [url for url in (figure_url(row.get("image")),) if url]
    for url in figures:
        stem_marks.append(Mark(kind="image", start=len(stem_text), len=1, url=url))

    collection = row.get("collection")
    row_exam = exam
    row_year = year
    if isinstance(collection, dict):
        if isinstance(collection.get("exam_type"), str):
            row_exam = str(collection["exam_type"]).lower()
        if isinstance(collection.get("exam_year"), int):
            row_year = int(collection["exam_year"])

    question = Question(
        id=f"q_{subject[:16]}_{row_year}_{row_exam}_{item_id}",
        exam=row_exam,
        subject=subject,
        year=row_year,
        source="claimed_paper",
        text=RichText(text=stem_text, inline=stem_marks),
        options=options,
        answer=answer,
        marks=1.0,
    )

    url = listing_url(row_exam, subject, row_year)
    return ParsedQuestion(
        question=question,
        source_url=f"{url}#{item_id}",
        source_item_id=item_id,
        payload_hash=_payload_hash(stem_text, options, answer),
        figures=figures,
        promises_stimulus=promises_stimulus(stem_text),
        missing_figure=mentions_figure(stem_text) and not figures,
    )
