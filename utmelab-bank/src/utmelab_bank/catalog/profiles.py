"""Per-subject layout profiles.

Most differences between the PDFs are layout, not content: which marker starts
a topic, where the body lives, and whether a heading wraps. A profile states
those facts once so the parser stays one engine.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Section headings are not topics. They are dropped before the state machine.
DEFAULT_SECTION_RE = (
    r"^(?:SECTION\s+[A-Z]|PART\s+[IVX0-9]+|PAPER\s+[0-9]+|[A-Z]\.\s+[A-Z][A-Z ,&/-]+)$"
)

#: The end of the syllabus. Everything after this is a reading list or a
#: list of practical materials, not a topic.
STOP_MARKERS = (
    "SUGGESTED READING",
    "RECOMMENDED READING",
    "RECOMMENDED TEXT",
    "RECOMMENDED BOOK",
    "READING LIST",
    "READING TEXT",
    "REFERENCE BOOK",
    "REFERENCES",
    "TEXTBOOKS",
    "SELECTED TEXTS",
    "OTHER IMPORTANT INFORMATION",
    "USE OF CALCULATORS",
    "OTHER MATERIALS REQUIRED",
    "MATERIALS NEEDED",
    "LIST OF PRACTICALS",
    "PRACTICALS",
    "IWE ITUMO",
)


@dataclass(frozen=True, slots=True)
class Profile:
    """How one subject's PDF is laid out."""

    slug: str
    display: str
    topic_re: str
    subtopic_re: str | None = None
    topic_x_min: float = 0.0
    topic_x_max: float = 130.0
    topic_continuation_x_max: float | None = None
    topic_continuation_same_x: bool = False
    topic_continuation_independent: bool = False
    topic_continuation_words: int = 3
    topic_continuation_gap: float = 30.0
    allow_uppercase_continuations: bool = False
    continuation_line_gap: float | None = None
    strict_continuation: bool = False
    section_lines_can_continue: bool = False
    topic_name_stop_re: str | None = None
    subtopic_name_stop_re: str | None = None
    body_x_min: float = 0.0
    body_x_max: float = 600.0
    start_marker: str = "DETAILED SYLLABUS"
    sentence_split: bool = True
    allow_single_subtopic: bool = True
    heading_heuristic: bool = False
    allow_uppercase_headings: bool = False
    merge_duplicate_topics: bool = False
    strip_topic_markers: bool = False
    uppercase_continuation_in_body: bool = False
    bare_marker_topics: bool = False
    expected_topics: int | None = None
    section_re: str = DEFAULT_SECTION_RE

    def __post_init__(self) -> None:
        if self.body_x_min < 0 or self.body_x_max <= self.body_x_min:
            raise ValueError(f"{self.slug}: the body column is empty")


PROFILES: dict[str, Profile] = {
    "nigerian-history": Profile(
        slug="nigerian-history",
        display="Nigerian History",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        topic_x_max=130,
        topic_continuation_x_max=160,
        body_x_min=110,
        body_x_max=600,
        sentence_split=False,
        section_re=r"^(?:SECTION\s+[A-Z].*|PAPER\s+[0-9]+.*|[A-Z][A-Z ,&/()-]{3,})$",
    ),
    "health-education": Profile(
        slug="health-education",
        display="Health Education",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^\(([a-z0-9]+)\)\s*(.+)$",
        topic_x_max=130,
        topic_continuation_x_max=160,
        body_x_min=60,
        body_x_max=250,
        sentence_split=False,
    ),
    "physical-education": Profile(
        slug="physical-education",
        display="Physical Education",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^\(([a-z0-9]+)\)\s*(.+)$",
        topic_x_max=130,
        topic_continuation_x_max=160,
        body_x_min=60,
        body_x_max=250,
        sentence_split=False,
    ),
    "commerce": Profile(
        slug="commerce",
        display="Commerce",
        topic_re=r"^(\d+)\.?\s*(.*)$",
        subtopic_re=r"^([ivx]+)\.\s*(.+)$",
        subtopic_name_stop_re=(
            r"\s*[–:]\s+|\s+-\s+(?!(?i:commerce)\b)|\s+[A-Za-z]\.\s+|\s+\((?:[a-z]|[ivx]+)\)\s+"
        ),
        topic_x_max=130,
        topic_continuation_x_max=140,
        topic_continuation_gap=45.0,
        allow_uppercase_continuations=True,
        continuation_line_gap=35.0,
        strict_continuation=True,
        section_lines_can_continue=True,
        uppercase_continuation_in_body=True,
        bare_marker_topics=True,
        body_x_min=250,
        body_x_max=340,
        sentence_split=True,
        strip_topic_markers=True,
        expected_topics=16,
        section_re=r"^(?:[A-Z]\.\s+[A-Z][A-Za-z ]+|[A-Z][A-Z ,&/()-]{3,})$",
    ),
    "economics": Profile(
        slug="economics",
        display="Economics",
        topic_re=r"^(\d+)\.\s+(.+)$",
        topic_x_max=115,
        body_x_min=0,
        body_x_max=420,
        expected_topics=25,
    ),
    "office-practice": Profile(
        slug="office-practice",
        display="Office Practice",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^([ivx]+)\.\s*(.+)$",
        topic_x_max=135,
        topic_continuation_x_max=220,
        body_x_min=250,
        body_x_max=600,
        sentence_split=False,
    ),
    "book-keeping": Profile(
        slug="book-keeping",
        display="Book Keeping",
        topic_re=r"^(\d+)\.?\s+(.+)$",
        subtopic_re=r"^(\d+\.\d+)\s*(.+)$",
        topic_x_max=90,
        topic_continuation_x_max=200,
        topic_continuation_same_x=True,
        topic_continuation_independent=True,
        topic_name_stop_re=(
            r"\s+(?=(?:Definition|Meaning|Types?|Concept|Format|Uses|Preparation|"
            r"Classification|Importance|Features|Advantages|Disadvantages|Functions)\b)"
        ),
        body_x_min=0,
        body_x_max=600,
        sentence_split=False,
    ),
    "chemistry": Profile(
        slug="chemistry",
        display="Chemistry",
        topic_re=r"^(\d+\.\d+)\s+(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        topic_x_max=100,
        topic_continuation_x_max=350,
        topic_continuation_same_x=True,
        body_x_min=0,
        body_x_max=300,
        sentence_split=False,
        uppercase_continuation_in_body=True,
        expected_topics=26,
    ),
    "animal-husbandry": Profile(
        slug="animal-husbandry",
        display="Animal Husbandry",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        topic_x_min=150,
        topic_x_max=210,
        topic_continuation_x_max=210,
        topic_continuation_same_x=True,
        topic_continuation_independent=True,
        body_x_min=150,
        body_x_max=300,
        sentence_split=False,
        section_re=r"^(?:[A-Z]\.\s+[A-Z][A-Za-z ]+|[A-Z][A-Z ,&/()-]{3,})$",
    ),
    "biology": Profile(
        slug="biology",
        display="Biology",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        topic_x_max=140,
        topic_continuation_x_max=180,
        body_x_min=60,
        body_x_max=300,
        sentence_split=False,
        section_re=r"^(?:[A-Z]\.\s+[A-Z][A-Za-z ]+|[A-Z][A-Z ,&/()-]{3,})$",
    ),
    "agricultural-science": Profile(
        slug="agricultural-science",
        display="Agricultural Science",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        topic_x_max=130,
        topic_continuation_x_max=140,
        topic_continuation_same_x=True,
        topic_continuation_words=10,
        body_x_min=0,
        body_x_max=235,
        sentence_split=False,
    ),
    "general-mathematics": Profile(
        slug="general-mathematics",
        display="General Mathematics",
        topic_re=r"^\(([a-z])\)\s*(.+)$",
        subtopic_re=r"^\(([ivx]+)\)\s*(.+)$",
        topic_x_max=135,
        topic_continuation_x_max=260,
        body_x_min=230,
        body_x_max=400,
        sentence_split=True,
        continuation_line_gap=25.0,
        topic_name_stop_re=r"\s+(?=angles\b|The Gambia\b|histograms\b)",
    ),
    "technical-drawing": Profile(
        slug="technical-drawing",
        display="Technical Drawing",
        topic_re=r"^(\d+)\s+(.+)$",
        topic_x_max=90,
        topic_continuation_x_max=130,
        body_x_min=300,
        body_x_max=600,
        sentence_split=True,
    ),
    "geography": Profile(
        slug="geography",
        display="Geography",
        topic_re=r"^(?P<name>[(*A-Z].*)$",
        topic_x_min=115,
        topic_x_max=170,
        topic_continuation_x_max=200,
        topic_continuation_words=4,
        body_x_min=250,
        body_x_max=600,
        sentence_split=True,
        strip_topic_markers=True,
        section_re=r"^(?:[A-Z][A-Z ,&/()-]{3,})$",
    ),
    "data-processing": Profile(
        slug="data-processing",
        display="Data Processing",
        topic_re=r"^(\d+)\s+(.+)$",
        subtopic_re=r"^([ivx]+)\.\s*(.+)$",
        topic_x_max=90,
        topic_continuation_x_max=110,
        body_x_min=220,
        body_x_max=360,
        sentence_split=False,
        section_re=r"^(?:[A-Z][A-Z ,&/()-]{3,})$",
    ),
    "foods-and-nutrition": Profile(
        slug="foods-and-nutrition",
        display="Foods and Nutrition",
        topic_re=r"^\((\d+)\)\s*(.+)$",
        subtopic_re=r"^\(([a-z]+)\)\s*(.+)$",
        topic_x_max=130,
        topic_continuation_x_max=130,
        body_x_min=270,
        body_x_max=520,
        sentence_split=False,
        section_re=r"^(?:[IVX]+\.\s+[A-Z].*|[A-Z][A-Z ,&/()-]{3,})$",
    ),
    "catering-craft": Profile(
        slug="catering-craft",
        display="Catering Craft",
        topic_re=r"^([IVX]+)\.?\s*(.+)$",
        topic_x_min=130,
        topic_x_max=170,
        topic_continuation_x_max=350,
        topic_continuation_same_x=True,
        body_x_min=300,
        body_x_max=600,
        sentence_split=True,
    ),
    "hausa": Profile(
        slug="hausa",
        display="Hausa",
        topic_re=r"^\(([ivx]+)\)\s*(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        topic_x_max=90,
        body_x_min=0,
        body_x_max=600,
        sentence_split=False,
        start_marker="CONTENT OF PAPER 2",
    ),
    "igbo": Profile(
        slug="igbo",
        display="Igbo",
        topic_re=r"^(?P<name>Part [IVX]+: .+|Customs .+|Institutions .+)$",
        subtopic_re=r"^\(([a-z0-9]+)\)\s*(.+)$",
        topic_x_max=200,
        body_x_min=0,
        body_x_max=600,
        sentence_split=False,
        start_marker="Further details on the structure of the paper",
        section_re=r"^(?:Section|SECTION)\s+[A-Z].*$",
    ),
    "yoruba": Profile(
        slug="yoruba",
        display="Yoruba",
        topic_re=r"^(?P<name>.+)$",
        subtopic_re=r"^\(([ivx]+)\)\s*(.+)$",
        heading_heuristic=True,
        topic_x_min=60,
        topic_x_max=130,
        body_x_min=0,
        body_x_max=600,
        sentence_split=False,
        start_marker="CONTENT",
        section_re=r"^(?:Section|SECTION)\s+[A-Z].*$",
    ),
    "visual-arts": Profile(
        slug="visual-arts",
        display="Visual Arts",
        topic_re=r"^(?P<name>.+)$",
        subtopic_re=r"^\(([a-z0-9]+)\)\s*(.+)$",
        heading_heuristic=True,
        topic_x_min=60,
        topic_x_max=130,
        body_x_min=0,
        body_x_max=600,
        sentence_split=False,
        section_re=(
            r"^(?:PAPERS?\s+\d.*|Paper\s+\d.*|Part\s+[A-Z]\s*-.*|"
            r"[A-Z][A-Z ,&/()-]{3,})$"
        ),
    ),
    "civic-education": Profile(
        slug="civic-education",
        display="Civic Education",
        topic_re=r"^(\d+)\.?\s+(.+)$",
        subtopic_re=r"^(\d+)\)\s*(.+)$",
        topic_x_max=130,
        body_x_min=130,
        body_x_max=600,
        sentence_split=False,
    ),
    "computer-studies": Profile(
        slug="computer-studies",
        display="Computer Studies",
        topic_re=r"^(?P<name>[A-Z][A-Z /&-]{3,})$",
        subtopic_re=r"^\(([a-z0-9]+)\)\s*(.+)$",
        topic_x_min=90,
        topic_x_max=130,
        body_x_min=80,
        body_x_max=400,
        sentence_split=False,
        section_re=r"^(?:SECTION\s+[A-Z].*)$",
    ),
    "further-mathematics": Profile(
        slug="further-mathematics",
        display="Further Mathematics",
        topic_re=r"^\((\d+)\)\s*(.+)$",
        subtopic_re=r"^\(([ivx]+)\)\s*(.+)$",
        topic_x_max=130,
        body_x_min=200,
        body_x_max=380,
        sentence_split=False,
    ),
    "english-language": Profile(
        slug="english-language",
        display="English Language",
        topic_re=r"^(?P<name>.+)$",
        heading_heuristic=True,
        allow_uppercase_headings=True,
        merge_duplicate_topics=True,
        strip_topic_markers=True,
        topic_x_min=60,
        topic_x_max=200,
        body_x_min=0,
        body_x_max=600,
        sentence_split=True,
        topic_name_stop_re=r"\s+\(\d+ marks?\)",
        section_re=r"^(?:PAPER\s+[0-9]+.*|SECTION\s+[A-Z].*)$",
    ),
    "marketing": Profile(
        slug="marketing",
        display="Marketing",
        topic_re=r"^(\d+)\.?\s+(.+)$",
        subtopic_re=r"^\(([a-z0-9]+)\)\s*(.+)$",
        topic_x_max=130,
        topic_continuation_x_max=130,
        body_x_min=230,
        body_x_max=600,
        sentence_split=False,
    ),
    "government": Profile(
        slug="government",
        display="Government",
        topic_re=r"^(\d+)\.\s+(.+)$",
        subtopic_re=r"^\(([a-z0-9]+)\)\s*(.+)$",
        subtopic_name_stop_re=r"\.\s+",
        topic_x_max=80,
        body_x_min=90,
        body_x_max=500,
        strict_continuation=True,
        section_re=r"^SECTION\s+[A-Z]",
    ),
    "physics": Profile(
        slug="physics",
        display="Physics",
        topic_re=r"^(\d+)\.\s*(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        topic_x_max=90,
        topic_continuation_x_max=120,
        topic_continuation_same_x=True,
        body_x_min=0,
        body_x_max=280,
        sentence_split=False,
        merge_duplicate_topics=True,
    ),
}


def profile_for(slug: str, display: str | None = None) -> Profile:
    """The named profile, or the numbered-topic default for the rest."""
    profile = PROFILES.get(slug)
    if profile is not None:
        return profile
    return Profile(
        slug=slug,
        display=display or slug.replace("-", " ").title(),
        topic_re=r"^(\d+)\.\s+(.+)$",
        subtopic_re=r"^\(([a-z])\)\s*(.+)$",
        body_x_min=0,
        body_x_max=600,
        sentence_split=False,
    )


__all__ = ["PROFILES", "Profile", "STOP_MARKERS", "profile_for"]
