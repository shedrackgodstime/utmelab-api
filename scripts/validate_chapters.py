#!/usr/bin/env python3
"""Structural validator for textbook chapters in data/chapters/*.json.

Enforces docs/CONTENT-BOOK-SCHEMA.md: the hierarchy, RichText and inline
offsets, grounded provenance on every object, an answer and a solution and a
tier on every exercise, one section per exercise, the teaching block
vocabulary, and the writing rules the content contract already sets.

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
    "book_id",
    "learning_objectives",
    "sections",
    "exercises",
    "sources",
]

# A chapter that names an exam is exam scoped content, which the book schema
# exists to remove.
FORBIDDEN_TOP = {"exam", "subject", "topic_slug", "subtopic_slug", "placements"}

REQUIRED_PROVENANCE = ["publisher", "title", "url", "locator", "licence"]

KNOWN_BLOCK_TYPES = {
    "paragraph",
    "heading",
    "definition",
    "rule",
    "formula",
    "example",
    "figure",
    "table",
    "list",
    "callout",
    "summary",
    "exercise_ref",
    "glossary_entry",
}
CALLOUT_KINDS = {"key_concept", "warning", "law", "tip", "definition"}
EXERCISE_KINDS = {"numeric", "algebraic", "verbal", "application", "proof"}
EXERCISE_TIERS = {"warm_up", "core", "stretch"}
ANSWER_KINDS = {"expression", "explanation"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
        if not isinstance(value.get(key), str) or not value.get(key, "").strip():
            errors.append((path, f"provenance.{key} missing or empty"))
    url = value.get("url")
    if isinstance(url, str) and url.strip() and not url.startswith(("http://", "https://")):
        errors.append((path, "provenance.url is not an absolute http(s) url"))


def check_blocks(blocks, path, errors, exercise_ids):
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
            continue
        if block_type == "paragraph":
            check_richtext(block.get("content"), f"{path}[{block_id}].content", errors)
        elif block_type == "heading":
            check_richtext(block.get("text"), f"{path}[{block_id}].text", errors)
        elif block_type == "definition":
            check_richtext(block.get("term"), f"{path}[{block_id}].term", errors)
            check_richtext(block.get("definition"), f"{path}[{block_id}].definition", errors)
        elif block_type == "rule":
            check_richtext(block.get("statement"), f"{path}[{block_id}].statement", errors)
            check_richtext(block.get("conditions"), f"{path}[{block_id}].conditions", errors)
        elif block_type == "formula":
            if not isinstance(block.get("expression"), str) or not block.get("expression", "").strip():
                errors.append((path, f"{path}[{block_id}] formula has no expression"))
            check_richtext(block.get("caption"), f"{path}[{block_id}].caption", errors)
        elif block_type == "callout":
            if block.get("kind") not in CALLOUT_KINDS:
                errors.append((path, f"{path}[{block_id}] callout kind {block.get('kind')!r} unknown"))
            check_richtext(block.get("text"), f"{path}[{block_id}].text", errors)
        elif block_type == "figure":
            asset = block.get("asset_url")
            if not isinstance(asset, str) or not asset.strip():
                errors.append((path, f"{path}[{block_id}] figure has no asset_url"))
            elif not asset.startswith(("http://", "https://", "/", "images/", "assets/")):
                errors.append((path, f"{path}[{block_id}] figure asset_url is not a usable path"))
            check_richtext(block.get("caption"), f"{path}[{block_id}].caption", errors)
            if not isinstance(block.get("alt"), str) or not block.get("alt", "").strip():
                errors.append((path, f"{path}[{block_id}] figure has no alt text"))
        elif block_type == "table":
            if not isinstance(block.get("rows"), list) or not block.get("rows"):
                errors.append((path, f"{path}[{block_id}] table has no rows"))
            check_richtext(block.get("title"), f"{path}[{block_id}].title", errors)
        elif block_type == "list":
            if not isinstance(block.get("items"), list) or not block.get("items"):
                errors.append((path, f"{path}[{block_id}] list has no items"))
        elif block_type == "summary":
            for point in block.get("points", []) or []:
                check_richtext(point, f"{path}[{block_id}].points", errors)
        elif block_type == "exercise_ref":
            if block.get("exercise_id") not in exercise_ids:
                errors.append((path, f"{path}[{block_id}] exercise_ref points at an unknown exercise"))
            check_richtext(block.get("prompt"), f"{path}[{block_id}].prompt", errors)
        elif block_type == "glossary_entry":
            check_richtext(block.get("term"), f"{path}[{block_id}].term", errors)
            check_richtext(block.get("definition"), f"{path}[{block_id}].definition", errors)


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

    if document.get("schema_version") != 2:
        errors.append((path, "schema_version != 2"))
    updated_at = document.get("updated_at")
    if not isinstance(updated_at, str) or not DATE_RE.match(updated_at or ""):
        errors.append((path, "updated_at is not YYYY-MM-DD"))
    if not isinstance(document.get("book_id"), str) or not document.get("book_id", "").strip():
        errors.append((path, "book_id missing"))

    # ---- chapter level
    objectives = document.get("learning_objectives")
    objective_ids = set()
    if not isinstance(objectives, list) or len(objectives) < 2:
        errors.append((path, "learning_objectives needs at least two entries"))
    else:
        for objective in objectives:
            if not isinstance(objective, dict):
                errors.append((path, "learning objective not dict"))
                continue
            objective_id = objective.get("id")
            if not isinstance(objective_id, str) or not objective_id:
                errors.append((path, "learning objective missing id"))
            elif objective_id in objective_ids:
                errors.append((path, f"duplicate learning objective id {objective_id}"))
            else:
                objective_ids.add(objective_id)
            if not isinstance(objective.get("statement"), str) or not objective.get("statement", "").strip():
                errors.append((path, f"learning objective {objective_id} has no statement"))

    prerequisites = document.get("prerequisites")
    if prerequisites is not None and not isinstance(prerequisites, list):
        errors.append((path, "prerequisites must be a list of chapter ids"))

    formula_sheet = document.get("formula_sheet")
    if not isinstance(formula_sheet, list):
        errors.append((path, "formula_sheet must be a list"))
    else:
        for entry in formula_sheet:
            if not isinstance(entry, dict):
                errors.append((path, "formula sheet entry not dict"))
                continue
            if not isinstance(entry.get("expression"), str) or not entry.get("expression", "").strip():
                errors.append((path, "formula sheet entry has no expression"))
            check_richtext(entry.get("caption"), f"{path}.formula_sheet.caption", errors)
            check_provenance(entry.get("provenance"), f"{path}.formula_sheet.provenance", errors)

    glossary = document.get("glossary")
    if glossary is not None:
        if not isinstance(glossary, list):
            errors.append((path, "glossary must be a list"))
        else:
            for entry in glossary:
                if not isinstance(entry, dict):
                    errors.append((path, "glossary entry not dict"))
                    continue
                check_richtext(entry.get("term"), f"{path}.glossary.term", errors)
                check_richtext(entry.get("definition"), f"{path}.glossary.definition", errors)
                check_provenance(entry.get("provenance"), f"{path}.glossary.provenance", errors)

    # ---- exercises
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
        if exercise.get("kind") not in EXERCISE_KINDS:
            errors.append((path, f"exercise {exercise_id} kind {exercise.get('kind')} unknown"))
        if exercise.get("tier") not in EXERCISE_TIERS:
            errors.append((path, f"exercise {exercise_id} tier {exercise.get('tier')!r} unknown"))
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
        hints = exercise.get("hints")
        if hints is not None:
            if not isinstance(hints, list):
                errors.append((path, f"exercise {exercise_id} hints must be a list"))
            else:
                if len(hints) > 3:
                    errors.append((path, f"exercise {exercise_id} has more than three hints"))
                for number, hint in enumerate(hints, start=1):
                    if not isinstance(hint, dict):
                        errors.append((path, f"exercise {exercise_id} hint {number} not dict"))
                        continue
                    if hint.get("hint_number") != number:
                        errors.append((path, f"exercise {exercise_id} hint {number} out of order"))
                    check_richtext(hint.get("text"), f"{path}.{exercise_id}.hints[{number}]", errors)
        tags = exercise.get("tags")
        if not isinstance(tags, list) or not tags:
            errors.append((path, f"exercise {exercise_id} has no tags"))
        check_provenance(exercise.get("provenance"), f"{path}.{exercise_id}.provenance", errors)

    # ---- sections
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
        if not isinstance(section.get("slug"), str) or not section.get("slug", "").strip():
            errors.append((path, f"section {section_id} has no slug"))
        minutes = section.get("est_minutes")
        if not isinstance(minutes, int) or minutes <= 0:
            errors.append((path, f"section {section_id} est_minutes not positive"))
        section_objectives = section.get("learning_objectives")
        if not isinstance(section_objectives, list) or not section_objectives:
            errors.append((path, f"section {section_id} needs learning objectives"))
        else:
            for objective in section_objectives:
                if not isinstance(objective, dict) or not isinstance(objective.get("statement"), str):
                    errors.append((path, f"section {section_id} learning objective malformed"))
        teaching = section.get("teaching_text")
        if not isinstance(teaching, dict) or not teaching.get("blocks"):
            errors.append((path, f"section {section_id} has no teaching text"))
        else:
            check_blocks(teaching.get("blocks"), f"{path}.{section_id}.teaching_text.blocks", errors, exercise_ids)
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
                check_provenance(example.get("provenance"), f"{path}.{section_id}.worked.provenance", errors)
        for misconception in section.get("misconceptions", []) or []:
            if not isinstance(misconception, dict):
                errors.append((path, f"section {section_id} misconception not dict"))
                continue
            check_richtext(misconception.get("claim"), f"{path}.{section_id}.misconception.claim", errors)
            check_richtext(misconception.get("correction"), f"{path}.{section_id}.misconception.correction", errors)
            check_provenance(misconception.get("provenance"), f"{path}.{section_id}.misconception.provenance", errors)
        check_provenance(section.get("provenance"), f"{path}.{section_id}.provenance", errors)

    # every exercise is listed by its section, and every listed exercise exists
    listed = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for exercise_id in section.get("exercise_ids", []) or []:
            listed.append(exercise_id)
            if exercise_id not in exercise_ids:
                errors.append((path, f"section {section.get('id')} lists unknown exercise {exercise_id}"))
    for exercise in exercises:
        if isinstance(exercise, dict) and exercise.get("id") not in listed:
            errors.append((path, f"exercise {exercise.get('id')} is not listed by its section"))
    if len(listed) != len(set(listed)):
        errors.append((path, "an exercise is listed by more than one section"))

    # ---- the exam side
    for section in sections:
        if not isinstance(section, dict):
            continue
        for link in section.get("exam_links", []) or []:
            if not isinstance(link, dict):
                errors.append((path, f"section {section.get('id')} exam link not dict"))
                continue
            for key in ("exam", "subject", "topic_slug", "subtopic_slug"):
                if not isinstance(link.get(key), str) or not link.get(key, "").strip():
                    errors.append((path, f"section {section.get('id')} exam link missing {key}"))
            if link.get("status") not in {"covered", "partial", "not_catalogued"}:
                errors.append((path, f"section {section.get('id')} exam link status unknown"))
            if not isinstance(link.get("question_ids"), list):
                errors.append((path, f"section {section.get('id')} exam link question_ids must be a list"))

    traps = document.get("exam_traps", [])
    if traps is not None and not isinstance(traps, list):
        errors.append((path, "exam_traps must be a list"))
    else:
        seen_traps = set()
        for trap in traps or []:
            if not isinstance(trap, dict):
                errors.append((path, "exam trap not dict"))
                continue
            trap_id = trap.get("id")
            if not isinstance(trap_id, str) or not trap_id:
                errors.append((path, "exam trap missing id"))
            elif trap_id in seen_traps:
                errors.append((path, f"duplicate exam trap id {trap_id}"))
            else:
                seen_traps.add(trap_id)
            if not isinstance(trap.get("exam"), str) or not trap.get("exam", "").strip():
                errors.append((path, f"exam trap {trap_id} names no exam"))
            if trap.get("section_id") not in section_ids:
                errors.append((path, f"exam trap {trap_id} points at unknown section"))
            check_richtext(trap.get("misconception"), f"{path}.{trap_id}.misconception", errors)
            check_richtext(trap.get("correction"), f"{path}.{trap_id}.correction", errors)
            check_richtext(trap.get("signal"), f"{path}.{trap_id}.signal", errors)
            evidence = trap.get("paper_evidence")
            if not isinstance(evidence, dict):
                # A trap without paper evidence is a chapter misconception.
                errors.append((path, f"exam trap {trap_id} has no paper evidence"))
            else:
                if not isinstance(evidence.get("question_id"), str) or not evidence.get("question_id", "").strip():
                    errors.append((path, f"exam trap {trap_id} evidence has no question id"))
                status = trap.get("status")
                source = evidence.get("source")
                if status not in {"proven", "candidate"}:
                    errors.append((path, f"exam trap {trap_id} status {status!r} unknown"))
                elif status == "proven" and source == "authored":
                    errors.append((path, f"exam trap {trap_id} claims a paper but its evidence is our own question"))
                elif status == "candidate" and source != "authored":
                    errors.append((path, f"exam trap {trap_id} is a candidate but its evidence is a paper"))
            check_provenance(trap.get("provenance"), f"{path}.{trap_id}.provenance", errors)

    checks = document.get("exam_recall_checks", [])
    if checks is not None and not isinstance(checks, list):
        errors.append((path, "exam_recall_checks must be a list"))
    else:
        seen_checks = set()
        for check in checks or []:
            if not isinstance(check, dict):
                errors.append((path, "recall check not dict"))
                continue
            check_id = check.get("id")
            if not isinstance(check_id, str) or not check_id:
                errors.append((path, "recall check missing id"))
            elif check_id in seen_checks:
                errors.append((path, f"duplicate recall check id {check_id}"))
            else:
                seen_checks.add(check_id)
            if not isinstance(check.get("exam"), str) or not check.get("exam", "").strip():
                errors.append((path, f"recall check {check_id} names no exam"))
            if check.get("section_id") not in section_ids:
                errors.append((path, f"recall check {check_id} points at unknown section"))
            check_richtext(check.get("stem"), f"{path}.{check_id}.stem", errors)
            check_richtext(check.get("explanation"), f"{path}.{check_id}.explanation", errors)
            options = check.get("options")
            if not isinstance(options, list) or len(options) < 2:
                errors.append((path, f"recall check {check_id} needs at least two options"))
            else:
                ids = []
                for option in options:
                    if not isinstance(option, dict) or not isinstance(option.get("id"), str):
                        errors.append((path, f"recall check {check_id} option is malformed"))
                        continue
                    if not isinstance(option.get("text"), str) or not option.get("text", "").strip():
                        errors.append((path, f"recall check {check_id} option has no text"))
                    ids.append(option["id"])
                if check.get("answer") not in ids:
                    errors.append((path, f"recall check {check_id} answer is not one of its options"))
            difficulty = check.get("difficulty")
            if not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
                errors.append((path, f"recall check {check_id} difficulty out of range"))

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
            collect_text(section.get("learning_objectives"), authored)
            collect_text(section.get("misconceptions"), authored)
            collect_text(section.get("summary_points"), authored)
    for chunk in authored:
        check_style(chunk, path, errors)

    return errors


REQUIRED_BOOK = ["book_id", "schema_version", "title", "subject_area", "level", "parts", "chapters", "sources"]


def validate_book(path):
    """A book document: the parts it divides into and the chapters it holds."""
    errors = []
    try:
        document = json.loads(Path(path).read_text())
    except Exception as error:
        return [(path, f"json parse: {error}")]
    for key in REQUIRED_BOOK:
        if key not in document:
            errors.append((path, f"missing {key}"))
    if document.get("schema_version") != 2:
        errors.append((path, "schema_version != 2"))
    parts = document.get("parts")
    if not isinstance(parts, list) or not parts:
        errors.append((path, "a book needs at least one part"))
    else:
        for index, part in enumerate(parts, start=1):
            if not isinstance(part, dict):
                errors.append((path, "part not dict"))
                continue
            if part.get("order") != index:
                errors.append((path, f"part {part.get('id')} order {part.get('order')} != {index}"))
            if not isinstance(part.get("title"), str) or not part.get("title", "").strip():
                errors.append((path, f"part {part.get('id')} has no title"))
    chapters = document.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        errors.append((path, "a book needs at least one chapter"))
    else:
        for chapter_id in chapters:
            path_on_disk = Path(__file__).resolve().parent.parent / "data/chapters" / f"{chapter_id}.json"
            if not path_on_disk.exists():
                errors.append((path, f"chapter {chapter_id} has no document"))
    sources = document.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append((path, "sources missing or empty"))
    else:
        for source in sources:
            check_provenance(source, f"{path}.sources", errors)
    return errors


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "data/chapters/*.json"
    paths = sorted(p for p in glob.glob(pattern) if not Path(p).name.startswith("_"))
    all_errors = []
    for path in paths:
        all_errors.extend(validate(path))
    if pattern == "data/chapters/*.json":
        for book in sorted(glob.glob("data/books/*.json")):
            all_errors.extend(validate_book(book))
    print("files", len(paths))
    print("errors", len(all_errors))
    for message, count in Counter(m for _, m in all_errors).most_common(20):
        print(count, message)
    for error in all_errors[:60]:
        print(error[0], "=>", error[1])
    raise SystemExit(1 if all_errors else 0)


if __name__ == "__main__":
    main()
