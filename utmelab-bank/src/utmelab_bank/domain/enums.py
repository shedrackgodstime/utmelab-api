"""Fixed vocabulary for the pipeline. These names are part of the contract."""

from enum import StrEnum


class Capability(StrEnum):
    DESCRIBE_IMAGE = "describe_image"
    EXPLAIN = "explain"
    TAG = "tag"
    VERIFY_ANSWER = "verify_answer"


class SourceCapability(StrEnum):
    PASSAGES = "passages"
    PASSAGE_SETS = "passage_sets"
    FIGURES = "figures"
    OPTION_FIGURES = "option_figures"
    RICH_TEXT = "rich_text"
    ANSWER = "answer"
    EXPLANATION = "explanation"
    SECTIONS = "sections"
    MARKS = "marks"


class State(StrEnum):
    """Where a piece of content is in the pipeline.

    The pipeline is a loop. ``live`` is content the bank handed over and
    production serves, and it is not the end: a report or a drift brings it
    back to ``enriched`` to be looked at again.
    """

    PLANNED = "planned"
    ACQUIRED = "acquired"
    ADAPTED = "adapted"
    GATED = "gated"
    DEDUPED = "deduped"
    CATALOGUED = "catalogued"
    MEDIA_READY = "media_ready"
    DESCRIBED = "described"
    ENRICHED = "enriched"
    VERIFIED = "verified"
    READY = "ready"
    LIVE = "live"
    REPORTED = "reported"
    REJECTED = "rejected"
    FAILED = "failed"


class InlineKind(StrEnum):
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKE = "strike"
    SUBSCRIPT = "subscript"
    SUPERSCRIPT = "superscript"
    IMAGE = "image"


class ImagePosition(StrEnum):
    """Where a figure sits relative to the text that inline it."""

    ABOVE = "above"
    BELOW = "below"


class PassageKind(StrEnum):
    """How a passage is to be read.

    The values are production's, spelled exactly as production spells them,
    because the kind is what tells a consumer how to read the passage. A
    cloze carries its gaps in the plain text. A data passage is numbers. A
    comprehension is a story or an article.

    The list is closed on purpose. A kind nobody can read is not a kind, and
    a new one is a one line change here and a new decision about what it
    means.
    """

    COMPREHENSION = "Comprehension"
    CLOZE = "Cloze"
    READING_TEXT = "ReadingText"
    DATA = "Data"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"


class VerificationKind(StrEnum):
    """Who checked, and how carefully.

    The values are production's, spelled as production spells them, because
    the kind is what the serving predicate reads. A bulk run and a single
    careful check are different evidence, and the kind is where that
    difference lives.

    Only ``HUMAN`` makes a row servable. The others are signal: they tell a
    reviewer what the machine thought, and they are the evidence behind a
    decision about whether the machine is good enough to be believed.
    """

    AUTO_RULE = "auto_rule"
    AI_BULK = "ai_bulk"
    AI_SINGLE = "ai_single"
    HUMAN = "human"


class Severity(StrEnum):
    """How hard a gate issue is.

    ``ERROR`` is a defect. It blocks, and only a fix to the content clears it.
    ``JUDGEMENT`` also blocks, but a person can clear it with a recorded
    reason, because some rules cannot tell a real defect from an ordinary
    word. ``WARNING`` does not block, and the gate does not use it for rules.
    """

    ERROR = "error"
    JUDGEMENT = "judgement"
    WARNING = "warning"
