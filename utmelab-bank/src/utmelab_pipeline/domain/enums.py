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
    REJECTED = "rejected"
    FAILED = "failed"


class MarkKind(StrEnum):
    BOLD = "bold"
    ITALIC = "italic"
    UNDERLINE = "underline"
    STRIKE = "strike"
    SUBSCRIPT = "subscript"
    SUPERSCRIPT = "superscript"
    IMAGE = "image"


class ImagePosition(StrEnum):
    """Where a figure sits relative to the text that marks it."""

    ABOVE = "above"
    BELOW = "below"


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"


class VerificationKind(StrEnum):
    AI = "ai"
    HUMAN = "human"


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"
