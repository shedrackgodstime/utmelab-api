"""Prune the catalog to a candidate set the model can actually reason about.

The full production catalog for one subject is large: JAMB Biology alone has
23 topics and 83 subtopics, each with objectives. Sending all of it in one
prompt is slow and wasteful. The model must still choose from the exact list,
so the ids and names always go through. The objectives only go through for the
candidates that look relevant.
"""

from __future__ import annotations

import re

from utmelab_pipeline.domain.models import CatalogSnapshot

_WORD = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "which",
        "with",
    }
)


def _words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


def _overlap(query: set[str], text: str) -> int:
    if not query:
        return 0
    return len(query & _words(text))


def candidate_ids(
    catalog: CatalogSnapshot,
    question: str,
    *,
    max_candidates: int = 12,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the topic and subtopic ids worth showing objectives for.

    The whole catalog is always valid. This only decides which ones carry
    their objectives into the prompt.
    """
    query = _words(question)
    scored_subtopics = [
        (_overlap(query, f"{subtopic.name} {' '.join(subtopic.objectives)}"), subtopic)
        for subtopic in catalog.subtopics
    ]
    ranked = sorted(scored_subtopics, key=lambda pair: (-pair[0], pair[1].id))
    keep_subtopics = tuple(
        subtopic.id for score, subtopic in ranked if score > 0
    )[:max_candidates]
    if not keep_subtopics:
        keep_subtopics = tuple(subtopic.id for _, subtopic in ranked[:max_candidates])

    scored_topics = [
        (_overlap(query, f"{topic.name} {' '.join(topic.objectives)}"), topic)
        for topic in catalog.topics
    ]
    ranked_topics = sorted(scored_topics, key=lambda pair: (-pair[0], pair[1].id))
    keep_topics = tuple(topic.id for score, topic in ranked_topics if score > 0)[
        :max_candidates
    ]
    if not keep_topics:
        keep_topics = tuple(topic.id for _, topic in ranked_topics[:max_candidates])
    return keep_topics, keep_subtopics


def catalog_for_prompt(
    catalog: CatalogSnapshot,
    question: str,
    *,
    max_candidates: int = 12,
) -> dict[str, object]:
    """Build the catalog block the model sees.

    Every topic and subtopic keeps its id, name and parent. Only the objectives
    of the candidate set are included, so the model still chooses from the exact
    list without carrying the whole syllabus.
    """
    keep_topics, keep_subtopics = candidate_ids(
        catalog,
        question,
        max_candidates=max_candidates,
    )
    return {
        "version": catalog.version,
        "topics": [
            {
                "id": topic.id,
                "name": topic.name,
                **(
                    {"objectives": list(topic.objectives)}
                    if topic.id in keep_topics
                    else {}
                ),
            }
            for topic in catalog.topics
        ],
        "subtopics": [
            {
                "id": subtopic.id,
                "name": subtopic.name,
                "topic_id": subtopic.topic_id,
                **(
                    {"objectives": list(subtopic.objectives)}
                    if subtopic.id in keep_subtopics
                    else {}
                ),
            }
            for subtopic in catalog.subtopics
        ],
    }
