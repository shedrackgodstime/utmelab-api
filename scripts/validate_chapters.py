#!/usr/bin/env python3
"""Structural validator for textbook chapters in data/chapters/*.json.

Enforces docs/CONTENT-CHAPTER-SPEC.md: exam independence at the chapter root,
RichText and inline offsets, grounded provenance on every object, an answer
and a solution on every exercise, one section per exercise, resolvable exam
links, and the writing rules the content contract already sets.

Usage:
    python3 scripts/validate_chapters.py [data/chapters/*.json]
"""
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

REQUIRED_TOP = [
    "chapter_id",
    "schema_version",
    "updated_at",
    "title",
    "book",
    "learning_objectives",
    "sections",
    "exercises",
    "exam_links",
    "sources",
]

# A chapter that names an exam at the root is exam-scoped content, which is
# exactly what the chapter model removes.
FORBIDDEN_TOP = {"exam", "subject", "topic_slug", "subtopic_slug", "placements"}

REQUIRED_BOOK = ["id", "title", "subject_area", "level"]
REQUIRED_PROVENANCE = ["publisher", "title", "url", "locator", "licence"]
KNOWN_BLOCK_TYPES = {
    "paragraph",
    "definition",
    "formula",
    "table",
    "list",
    "summary",
    "example",
    "exercise",
    "heading",
    "theorem",
    "proof",
    "procedure",
    "figure",
    "passage",
    "cloze",
    "quote",
    "media",
    "glossary_entry",
}
EXERCISE_KINDS = {"numeric", "algebraic", "verbal", "application"}
ANSWER_KINDS = {"expression", "explanation"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Writing rules from docs/CONTENT-WORKFLOW-CONTRACT.md.
BANNED_PHRASES = [
    "delve",
    "it is important to note",
    "it should be noted",
    "in conclusion",
    "moreover",
    "furthermore",
    "unlock",
    "leverage",
]
DASHES = {"—": "em dash", "–": "en dash"}


def is_richtext(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("text"), str)
        and isinstance(value.get("inline"), list)
    )


def check_richtext(value, path, errors):
    if not is_richtext(value):
        errors.append((path, "not richtext"))
        return
    text = value["text"]
    length = len(text)
    for item in value.get("inline", []):
        if not isinstance(item, dict):
            errors.append((path, "inline item not dict"))
            continue
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            errors.append((path, "inline offsets not integers"))
            continue
        if start < 0 or end < start or end > length:
            errors.append((path, f"inline offset invalid {start},{end},len={length}"))


def check_provenance(value, path, errors):
    if not isinstance(value, dict):
        errors.append((path, "provenance not dict"))
        return
    for key in REQUIRED_PROVENANCE:
        if not isinstance(value.get(key), str) or not value.get(key).strip():
            errors.append((path, f"provenance.{key} missing or empty"))
    url = value.get("url")
    if isinstance(url, str) and url.strip() and not url.startswith(("http://", "https://")):
        errors.append((path, "provenance.url is not an absolute http(s) url"))


def check_blocks(blocks, path, errors):
    if not isinstance(blocks, list):
        errors.append((path, "blocks not list"))
        return
    seen = set()
    for block in blocks:
        if not isinstance(block, dict):
            errors.append((path, "block not dict"))
            continue
        block_id = block.get("id")
        if not isinstance(block_id, str) or not block_id:
            errors.append((path, "block missing id"))
        elif block_id in seen:
            errors.append((path, f"duplicate block id {block_id}"))
        else:
            seen.add(block_id)
        block_type = block.get("type")
        if block_type not in KNOWN_BLOCK_TYPES:
            errors.append((path, f"unknown block type {block_type}"))
        if block_type == "paragraph":
            check_richtext(block.get("content"), f"{path}[{block_id}].content", errors)
        elif block_type == "definition":
            check_richtext(block.get("term"), f"{path}[{block_id}].term", errors)
            check_richtext(block.get("definition"), f"{path}[{block_id}].definition", errors)
        elif block_type == "formula":
            if not isinstance(block.get("expression"), str) or not block.get("expression", "").strip():
                errors.append((path, f"{path}[{block_id}] formula has no expression"))
            check_richtext(block.get("caption"), f"{path}[{block_id}].caption", errors)
        elif block_type == "figure":
            asset = block.get("asset_url")
            if not isinstance(asset, str) or not asset.strip():
                errors.append((path, f"{path}[{block_id}] figure has no asset_url"))
            elif not asset.startswith(("http://", "https://", "/", "images/", "assets/")):
                errors.append((path, f"{path}[{block_id}] figure asset_url is not a usable path"))
            check_richtext(block.get("caption"), f"{path}[{block_id}].caption", errors)
            if not isinstance(block.get("alt"), str) or not block.get("alt", "").strip():
                errors.append((path, f"{path}[{block_id}] figure has no alt text"))
        elif block_type == "summary":
            for point in block.get("points", []) or []:
                check_richtext(point, f"{path}[{block_id}].points", errors)


def check_style(text, path, errors):
    for character, name in DASHES.items():
        if character in text:
            errors.append((path, f"{name} in content"))
    lowered = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            errors.append((path, f"banned phrase '{phrase}'"))


def collect_text(value, sink):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "text" and isinstance(item, str):
                sink.append(item)
            else:
                collect_text(item, sink)
    elif isinstance(value, list):
        for item in value:
            collect_text(item, sink)


def validate(path):
    errors = []
    try:
        document = json.loads(Path(path).read_text())
    except Exception as error:
        return [(path, f"json parse: {error}")]

    for key in REQUIRED_TOP:
        if key not in document:
            errors.append((path, f"missing {key}"))
    for key in FORBIDDEN_TOP:
        if key in document:
            errors.append((path, f"exam scoped key '{key}' at chapter root"))

    if document.get("schema_version") != 1:
        errors.append((path, "schema_version != 1"))
    updated_at = document.get("updated_at")
    if not isinstance(updated_at, str) or not DATE_RE.match(updated_at or ""):
        errors.append((path, "updated_at is not YYYY-MM-DD"))

    book = document.get("book")
    if not isinstance(book, dict):
        errors.append((path, "book not dict"))
    else:
        for key in REQUIRED_BOOK:
            if not isinstance(book.get(key), str) or not book.get(key, "").strip():
                errors.append((path, f"book.{key} missing or empty"))

    objectives = document.get("learning_objectives")
    if not isinstance(objectives, list) or len(objectives) < 2:
        errors.append((path, "learning_objectives needs at least two entries"))
    else:
        ids = set()
        for objective in objectives:
            if not isinstance(objective, dict):
                errors.append((path, "learning objective not dict"))
                continue
            objective_id = objective.get("id")
            if not isinstance(objective_id, str) or not objective_id:
                errors.append((path, "learning objective missing id"))
            elif objective_id in ids:
                errors.append((path, f"duplicate learning objective id {objective_id}"))
            else:
                ids.add(objective_id)
            statement = objective.get("statement")
            if not isinstance(statement, str) or not statement.strip():
                errors.append((path, f"learning objective {objective_id} has no statement"))

    sections = document.get("sections")
    section_ids = set()
    if not isinstance(sections, list) or not sections:
        errors.append((path, "sections missing or empty"))
        sections = []
    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            errors.append((path, "section not dict"))
            continue
        section_id = section.get("id")
        if not isinstance(section_id, str) or not section_id:
            errors.append((path, "section missing id"))
        elif section_id in section_ids:
            errors.append((path, f"duplicate section id {section_id}"))
        else:
            section_ids.add(section_id)
        if section.get("order") != index:
            errors.append((path, f"section {section_id} order {section.get('order')} != {index}"))
        if not isinstance(section.get("title"), str) or not section.get("title", "").strip():
            errors.append((path, f"section {section_id} has no title"))
        minutes = section.get("est_minutes")
        if not isinstance(minutes, int) or minutes <= 0:
            errors.append((path, f"section {section_id} est_minutes not positive"))
        teaching = section.get("teaching_text")
        if not isinstance(teaching, dict) or not teaching.get("blocks"):
            errors.append((path, f"section {section_id} has no teaching text"))
        else:
            check_blocks(teaching.get("blocks"), f"{path}.{section_id}.teaching_text.blocks", errors)
        summary = section.get("summary_points")
        if not isinstance(summary, list) or len(summary) < 2:
            errors.append((path, f"section {section_id} needs at least two summary points"))
        else:
            for point in summary:
                check_richtext(point, f"{path}.{section_id}.summary_points", errors)
        worked = section.get("worked_examples")
        reason = section.get("no_worked_example_reason")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            errors.append((path, f"section {section_id} no_worked_example_reason is empty"))
        if not isinstance(worked, list) or not worked:
            if not (isinstance(reason, str) and reason.strip()):
                errors.append((path, f"section {section_id} needs a worked example"))
        else:
            for example in worked:
                if not isinstance(example, dict):
                    errors.append((path, f"section {section_id} worked example not dict"))
                    continue
                check_richtext(example.get("statement"), f"{path}.{section_id}.worked.statement", errors)
                check_richtext(example.get("answer"), f"{path}.{section_id}.worked.answer", errors)
                steps = example.get("steps")
                if not isinstance(steps, list) or not steps:
                    errors.append((path, f"section {section_id} worked example has no steps"))
                else:
                    for step in steps:
                        if not isinstance(step, dict) or not isinstance(step.get("expression"), str):
                            errors.append((path, f"section {section_id} worked example step malformed"))
                check_provenance(example.get("provenance"), f"{path}.{section_id}.worked.provenance", errors)
        for misconception in section.get("misconceptions", []) or []:
            if not isinstance(misconception, dict):
                errors.append((path, f"section {section_id} misconception not dict"))
                continue
            check_richtext(misconception.get("claim"), f"{path}.{section_id}.misconception.claim", errors)
            check_richtext(misconception.get("correction"), f"{path}.{section_id}.misconception.correction", errors)
            check_provenance(misconception.get("provenance"), f"{path}.{section_id}.misconception.provenance", errors)
        check_provenance(section.get("provenance"), f"{path}.{section_id}.provenance", errors)

    exercises = document.get("exercises")
    exercise_ids = set()
    if not isinstance(exercises, list) or not exercises:
        errors.append((path, "exercises missing or empty"))
        exercises = []
    for exercise in exercises:
        if not isinstance(exercise, dict):
            errors.append((path, "exercise not dict"))
            continue
        exercise_id = exercise.get("id")
        if not isinstance(exercise_id, str) or not exercise_id:
            errors.append((path, "exercise missing id"))
        elif exercise_id in exercise_ids:
            errors.append((path, f"duplicate exercise id {exercise_id}"))
        else:
            exercise_ids.add(exercise_id)
        section_id = exercise.get("section_id")
        if section_id not in section_ids:
            errors.append((path, f"exercise {exercise_id} points at unknown section {section_id}"))
        if exercise.get("kind") not in EXERCISE_KINDS:
            errors.append((path, f"exercise {exercise_id} kind {exercise.get('kind')} unknown"))
        difficulty = exercise.get("difficulty")
        if not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
            errors.append((path, f"exercise {exercise_id} difficulty out of range"))
        marks = exercise.get("marks")
        if not isinstance(marks, (int, float)) or marks <= 0:
            errors.append((path, f"exercise {exercise_id} marks not positive"))
        check_richtext(exercise.get("stem"), f"{path}.{exercise_id}.stem", errors)
        check_richtext(exercise.get("answer"), f"{path}.{exercise_id}.answer", errors)
        if exercise.get("answer_kind") not in ANSWER_KINDS:
            errors.append((path, f"exercise {exercise_id} answer_kind {exercise.get('answer_kind')} unknown"))
        solution = exercise.get("solution")
        if not isinstance(solution, list) or not solution:
            errors.append((path, f"exercise {exercise_id} has no solution"))
        else:
            for number, step in enumerate(solution, start=1):
                if not isinstance(step, dict) or not isinstance(step.get("expression"), str) or not step["expression"].strip():
                    errors.append((path, f"exercise {exercise_id} solution step {number} malformed"))
                elif step.get("step_number") != number:
                    errors.append((path, f"exercise {exercise_id} solution step {number} out of order"))
        tags = exercise.get("tags")
        if not isinstance(tags, list) or not tags:
            errors.append((path, f"exercise {exercise_id} has no tags"))
        check_provenance(exercise.get("provenance"), f"{path}.{exercise_id}.provenance", errors)

    listed = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for exercise_id in section.get("practice_exercise_ids", []) or []:
            listed.append(exercise_id)
            if exercise_id not in exercise_ids:
                errors.append((path, f"section {section.get('id')} lists unknown exercise {exercise_id}"))
    for exercise in exercises:
        if isinstance(exercise, dict) and exercise.get("id") not in listed:
            errors.append((path, f"exercise {exercise.get('id')} is not listed by its section"))
    if len(listed) != len(set(listed)):
        errors.append((path, "an exercise is listed by more than one section"))

    links = document.get("exam_links")
    if not isinstance(links, list) or not links:
        errors.append((path, "exam_links missing or empty"))
    else:
        for link in links:
            if not isinstance(link, dict):
                errors.append((path, "exam link not dict"))
                continue
            for key in ("exam", "subject"):
                if not isinstance(link.get(key), str) or not link.get(key, "").strip():
                    errors.append((path, f"exam link missing {key}"))
            topic = link.get("topic_slug")
            status = link.get("status")
            if status not in {"covered", "partial", "not_catalogued"}:
                errors.append((path, f"exam link status {status!r} unknown"))
            if topic is None:
                # A subject level link is only honest when the exam's catalog
                # for that subject has not been built yet.
                if status != "not_catalogued":
                    errors.append((path, "exam link without a topic must be not_catalogued"))
            elif not isinstance(topic, str) or not topic.strip():
                errors.append((path, "exam link topic_slug must be a non-empty string or null"))
            subtopic = link.get("subtopic_slug")
            if subtopic is not None and not isinstance(subtopic, str):
                errors.append((path, "exam link subtopic_slug must be a string or null"))
            if not isinstance(link.get("question_ids"), list):
                errors.append((path, "exam link question_ids must be a list"))
            if not isinstance(link.get("source_locator"), str) or not link.get("source_locator", "").strip():
                errors.append((path, "exam link source_locator missing"))

    sources = document.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append((path, "sources missing or empty"))
    else:
        for source in sources:
            check_provenance(source, f"{path}.sources", errors)

    # The style rules apply to what we author. Teaching text is the source's
    # own prose, quoted with its provenance, and keeps the source's punctuation.
    authored = []
    collect_text(document.get("learning_objectives"), authored)
    for section in sections:
        if isinstance(section, dict):
            collect_text(section.get("misconceptions"), authored)
            collect_text(section.get("summary_points"), authored)
    for chunk in authored:
        check_style(chunk, path, errors)

    return errors


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "data/chapters/*.json"
    paths = sorted(p for p in glob.glob(pattern) if not Path(p).name.startswith("_"))
    all_errors = []
    for path in paths:
        all_errors.extend(validate(path))
    print("files", len(paths))
    print("errors", len(all_errors))
    for message, count in Counter(m for _, m in all_errors).most_common(20):
        print(count, message)
    for error in all_errors[:60]:
        print(error[0], "=>", error[1])
    raise SystemExit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
