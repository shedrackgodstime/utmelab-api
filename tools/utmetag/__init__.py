"""utmetag — a thin, provider-agnostic auto-tagging SDK for the question bank.

The model backend is a swappable ``Provider`` (see ``providers``). The task and
runner layers depend only on that protocol, so the "model API" part can be the
OpenCode CLI, an HTTP endpoint, or a mock without touching task logic.
"""

from __future__ import annotations

from .bank import filter_questions, get_subject_subtopics, get_subject_topics, load_bank
from .jsonio import extract_json
from .prompt import build_tagging_prompt
from .providers import (
    HTTPProvider,
    MockProvider,
    OpenCodeProvider,
    Provider,
    build_provider_with_cap,
)
from .runner import run, summarize
from .schema import (
    ModelOutput,
    QuestionInput,
    SubtopicInfo,
    TagResult,
    TopicInfo,
)
from .tasks import tag_question

__version__ = "0.1.0"

__all__ = [
    "Provider",
    "MockProvider",
    "OpenCodeProvider",
    "HTTPProvider",
    "build_provider_with_cap",
    "ModelOutput",
    "QuestionInput",
    "SubtopicInfo",
    "TagResult",
    "TopicInfo",
    "extract_json",
    "build_tagging_prompt",
    "tag_question",
    "run",
    "summarize",
    "load_bank",
    "filter_questions",
    "get_subject_subtopics",
    "get_subject_topics",
]
