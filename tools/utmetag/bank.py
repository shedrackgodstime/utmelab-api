"""Bank loading and filtering (provider-independent)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .schema import QuestionInput, SubtopicInfo, TopicInfo


def load_bank(data_dir: Path) -> dict:
    def read(name: str) -> Any:
        with open(data_dir / name) as f:
            return json.load(f)

    return {
        "questions": read("questions.json"),
        "subjects": read("subjects.json"),
        "topics": read("topics.json"),
        "subtopics": read("subtopics.json"),
        "passages": read("passages.json"),
        "verifications": read("verifications.json") if (data_dir / "verifications.json").exists() else [],
    }


def is_verified(bank: dict, question_id: str) -> bool:
    """A question counts as verified if a human row passes answer+explanation."""
    for v in bank.get("verifications", []):
        if v["question_id"] != question_id or v["kind"] != "human":
            continue
        scope = v.get("scope", [])
        if "answer" in scope and "explanation" in scope and v["verdict"] == "pass":
            return True
    return False


def filter_questions(
    bank: dict,
    subject: Optional[str],
    exam: str,
    limit: int,
    only_unverified: bool,
    question_ids: Optional[list[str]] = None,
) -> list[QuestionInput]:
    questions: list[QuestionInput] = []
    for q in bank["questions"]:
        if q["exam"] != exam:
            continue
        if subject and q["subject"] != subject:
            continue
        if question_ids and q["id"] not in question_ids:
            continue
        if only_unverified and is_verified(bank, q["id"]):
            continue
        questions.append(QuestionInput(
            id=q["id"],
            exam=q["exam"],
            subject=q["subject"],
            year=q["year"],
            source=q["source"],
            text=q["text"],
            options=q["options"],
            answer=q["answer"],
            subtopic_id=q.get("subtopic_id"),
            explanation=q.get("explanation"),
            marks=q.get("marks", 2.5),
            difficulty=q.get("difficulty", 3),
        ))
        if len(questions) >= limit:
            break
    return questions


def get_subject_subtopics(bank: dict, exam: str, subject: str) -> list[SubtopicInfo]:
    subtopics: list[SubtopicInfo] = []
    for st in bank["subtopics"]:
        parent = next((t for t in bank["topics"] if t["slug"] == st["topic"]), None)
        if parent and parent["exam"] == exam and parent["subject"] == subject:
            subtopics.append(SubtopicInfo(
                slug=st["slug"],
                topic=st["topic"],
                name=st["name"],
                objectives=st.get("objectives", []),
            ))
    return subtopics


def get_subject_topics(bank: dict, exam: str, subject: str) -> list[TopicInfo]:
    topics: list[TopicInfo] = []
    for t in bank["topics"]:
        if t["exam"] == exam and t["subject"] == subject:
            topics.append(TopicInfo(
                slug=t["slug"],
                name=t["name"],
                subject=t["subject"],
                exam=t["exam"],
                objectives=t.get("objectives", []),
            ))
    return topics
