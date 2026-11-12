#!/usr/bin/env python3
"""Build a textbook chapter from a chapter spec.

    python3 scripts/build_chapter.py data/chapter-specs/<chapter_id>.json
    python3 scripts/build_chapter.py data/chapter-specs/<chapter_id>.json --check

A spec carries what a human authors: the objectives, the misconceptions, the
summary points, the formula sheet, the glossary, the exam links, and any
teaching text we wrote ourselves. Everything else comes from the source: the
prose, the figures, the exercises, the answers and the solutions.

The spec is the source of truth for the authored part. The chapter document
is the built artifact, and the two are checked against each other in CI, so
the chapter can never drift from its spec.

See docs/CONTENT-BOOK-SCHEMA.md for the shapes.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONCEPTS = ROOT / "data/concepts"
SOLUTIONS = ROOT / "data/staging/openstax_clean_solutions.json"
CHAPTERS = ROOT / "data/chapters"
BOOKS = ROOT / "data/books"

TIERS = ("warm_up", "core", "stretch")


def rt(text):
    return {"text": text, "inline": []}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def load_solutions():
    if not SOLUTIONS.exists():
        return {}
    return json.loads(SOLUTIONS.read_text())


def find_concept(module):
    """The concept document built from a source module."""
    for path in sorted(CONCEPTS.glob("*.json")):
        if path.name.startswith("audit-"):
            continue
        try:
            document = json.loads(path.read_text())
        except Exception:
            continue
        source = document.get("source_attribution") or {}
        if (source.get("section") or "") == module:
            return document, path
    return None, None


def render_parts(parts):
    out = []
    for part in parts:
        if part["kind"] == "text":
            text = " ".join(part["text"].split())
            if text:
                out.append(text)
        else:
            out.append(f"${part['text']}$")
    return " ".join(out).strip()


def classify(prompt):
    text = prompt.lower()
    if "explain" in text or text.rstrip().endswith("why") or "discuss" in text:
        return "verbal"
    # A multi part problem is marked with two part markers.
    if (re.search(r"\(a\)", text) and re.search(r"\(b\)", text)) or ("ⓐ" in prompt and "ⓑ" in prompt):
        return "application"
    if re.search(r"\d", prompt):
        return "numeric"
    return "algebraic"


def answer_from(parts, kind):
    """The answer as the source states it, never a newly written one."""
    rendered = render_parts([p for paragraph in parts for p in paragraph])
    if kind == "verbal":
        return rendered, "explanation"
    candidates = [
        p["text"]
        for paragraph in parts
        for p in paragraph
        if p["kind"] == "math" and p["text"].strip()
    ]
    if not candidates:
        candidates = [
            p["text"]
            for paragraph in parts
            for p in paragraph
            if p["kind"] == "text" and p["text"].strip() and len(p["text"]) <= 40
        ]
    for candidate in reversed(candidates):
        value = candidate.strip().strip("$").strip()
        value = value.strip(" .,;:")
        if not value or "$" in value:
            continue
        if not re.search(r"[A-Za-z0-9]", value):
            continue
        # A short trailing fragment of a longer expression is not an answer.
        if len(value) < 12 and value[0] in "}^_":
            continue
        if "=" in value:
            tail = value.rsplit("=", 1)[1].strip().strip("$").strip(" .,;:")
            if tail and len(tail) <= 30 and "=" not in tail:
                return tail, "expression"
        # A chain of fractions ends with the answer.
        pieces = value.rsplit("\\cdot", 1)[-1]
        fractions = re.findall(r"\\frac\{(?:[^{}]|\{[^{}]*\})*\}\{(?:[^{}]|\{[^{}]*\})*\}", pieces)
        if len(fractions) > 1:
            return fractions[-1], "expression"
        if len(value) > 70:
            continue
        twins = [
            other.strip().strip("$").strip(" .,;:")
            for other in candidates
            if other is not candidate
        ]
        if value.startswith("-") and value[1:] in twins:
            # The source states both cases, a value and its opposite. The
            # whole solution is the honest answer.
            return rendered, "explanation"
        return value, "expression"
    return rendered, "explanation"


def tier_for(difficulty):
    if difficulty <= 2:
        return "warm_up"
    if difficulty == 3:
        return "core"
    return "stretch"


# The source groups its exercises by how hard they are meant to be. The tier
# comes from that grouping, not from our guess.
GROUP_TIERS = {
    "conceptual questions": "warm_up",
    "problems and exercises": "core",
    "problem exercises": "core",
    "section exercises": "core",
    "test prep for ap courses": "stretch",
}


def tier_for_grouping(grouping):
    return GROUP_TIERS.get((grouping or "").strip().lower(), "core")


def source_blocks(concept, module, solutions):
    """Teaching blocks, worked examples and exercises, from the source."""
    blocks = concept["deep_context"]["blocks"]
    source = concept.get("source_attribution") or {}
    book = source.get("book") or ""
    teaching = []
    worked = []
    exercises = []
    pending = None
    grouping = None

    def provenance(locator):
        return {
            "publisher": source.get("publisher") or "OpenStax",
            "title": source.get("title") or source.get("book") or "",
            "url": source.get("url") or "",
            "locator": locator,
            "licence": source.get("licence") or "",
        }

    for block in blocks:
        kind = block.get("type")
        if pending is not None and kind in ("heading", "example", "figure"):
            worked.append(pending)
            pending = None
        if kind == "heading":
            title = block["text"]["text"].strip()
            grouping = title
            if title in {"Learning Objectives", "Section Summary", "Conceptual Questions", "Test Prep for AP Courses"}:
                continue
            teaching.append({"id": f"b-{len(teaching) + 1}", "type": "heading", "text": rt(title)})
        elif kind == "paragraph":
            text = block["content"]["text"].strip()
            if text.startswith("By the end of this section, you will be able to"):
                continue
            if pending is not None:
                pending["solution"].append(text)
                continue
            teaching.append({"id": f"b-{len(teaching) + 1}", "type": "paragraph", "content": rt(text)})
        elif kind == "figure":
            teaching.append({
                "id": f"b-{len(teaching) + 1}",
                "type": "figure",
                "asset_url": block.get("asset_url"),
                "caption": block.get("caption") or rt(""),
                "alt": block.get("alt") or "",
                "licence": source.get("licence") or "",
            })
        elif kind == "example":
            pending = {
                "id": f"we-{block['id']}",
                "statement": rt((block.get("title") or {}).get("text", "")),
                "solution": [],
                "provenance": provenance(f"CNXML module {module}, worked example"),
            }
        elif kind == "exercise":
            key = f"{book}:{module}:{block['id']}"
            paragraphs = solutions.get(key)
            if not paragraphs:
                continue
            prompt = (block.get("prompt") or {}).get("text", "").strip()
            if not prompt:
                continue
            kind_label = classify(prompt)
            if kind_label == "application" or len(paragraphs) > 2:
                answer, answer_kind = render_parts(
                    [p for paragraph in paragraphs for p in paragraph]
                ), "explanation"
            else:
                answer, answer_kind = answer_from(paragraphs, kind_label)
            steps = []
            number = 0
            for paragraph in paragraphs:
                rendered = render_parts(paragraph)
                if rendered:
                    number += 1
                    steps.append({"step_number": number, "expression": rendered})
            exercises.append({
                "block_id": block["id"],
                "kind": kind_label,
                "stem": rt(prompt),
                "answer": rt(answer),
                "answer_kind": answer_kind,
                "solution": steps,
                "provenance": provenance(f"CNXML module {module}, exercise block {block['id']}"),
                "solution_provenance": "OpenStax CNXML solution element (in file)",
                "grouping": grouping,
            })

    if pending is not None:
        worked.append(pending)
    for item in worked:
        if item.get("solution"):
            sentences = [
                part.strip()
                for part in re.split(r"(?<=[.!?])\s+", " ".join(item["solution"]))
                if part.strip()
            ]
            item["steps"] = [
                {"step_number": number, "expression": sentence}
                for number, sentence in enumerate(sentences, start=1)
            ]
            item["answer"] = rt(" ".join(item["solution"]))
            item.pop("solution", None)
    # An example block with no prose after it is an empty shell. Its content
    # sits in the exercise nested inside it, and that exercise carries the
    # solution.
    worked = [item for item in worked if item.get("steps")]
    return teaching, worked, exercises


def build(spec):
    solutions = load_solutions()
    sections = []
    exercises = []
    number = 0

    for index, section_spec in enumerate(spec["sections"], start=1):
        section_id = section_spec["id"]
        module = section_spec.get("module")
        source_teaching = []
        source_worked = []
        source_exercises = []

        if module:
            concept, path = find_concept(module)
            if concept is None:
                raise SystemExit(f"no concept document for module {module}")
            source_teaching, source_worked, source_exercises = source_blocks(concept, module, solutions)

        teaching = list(source_teaching)
        for position, block in enumerate(section_spec.get("blocks", []), start=len(teaching) + 1):
            block = dict(block)
            block.setdefault("id", f"b-{position}")
            teaching.append(block)

        worked = list(source_worked)
        for item in section_spec.get("worked", []):
            worked.append(item)

        plan = section_spec.get("exercise_plan", {})
        promoted = section_spec.get("worked_from")
        section_exercises = []
        for source_exercise in source_exercises:
            if not source_exercise["solution"]:
                # The source has the exercise but nothing readable for the
                # solution. An exercise without a solution is not an
                # exercise.
                continue
            if promoted == source_exercise["block_id"]:
                # The spec promotes one solved exercise to the worked
                # example of the section, so it is shown worked rather than
                # left as practice.
                worked.append({
                    "id": f"we-{source_exercise['block_id']}",
                    "statement": source_exercise["stem"],
                    "steps": source_exercise["solution"],
                    "answer": source_exercise["answer"],
                    "provenance": source_exercise["provenance"],
                })
                continue
            if plan and source_exercise["block_id"] not in plan:
                # The spec selects the exercises it wants from the module.
                continue
            number += 1
            exercise_id = f"ex-{section_id}-{len(section_exercises) + 1:02d}"
            override = plan.get(source_exercise["block_id"], {})
            tier = override.get("tier", tier_for_grouping(source_exercise.get("grouping")))
            if tier == "core" and source_exercise.get("grouping", "").lower().startswith("problems") \
                    and source_exercise.get("kind") == "application":
                # A multi part problem is the stretch of the set.
                tier = "stretch"
            default_difficulty = {"warm_up": 1, "core": 3, "stretch": 4}.get(tier, 3)
            difficulty = override.get("difficulty", default_difficulty)
            marks = override.get("marks", max(1, min(5, difficulty)))
            kind = override.get("kind", source_exercise["kind"])
            exercise = {
                "id": exercise_id,
                "section_id": section_id,
                "tier": tier,
                "kind": kind,
                "difficulty": difficulty,
                "marks": marks,
                "stem": source_exercise["stem"],
                "options": override.get("options", []),
                "answer": source_exercise["answer"],
                "answer_kind": source_exercise["answer_kind"],
                "solution": source_exercise["solution"],
                "tags": section_spec.get("tags", []),
                "provenance": source_exercise["provenance"],
                "solution_provenance": source_exercise["solution_provenance"],
            }
            hints = override.get("hints")
            if hints:
                exercise["hints"] = [
                    {"hint_number": index + 1, "text": rt(hint)}
                    for index, hint in enumerate(hints)
                ]
            section_exercises.append(exercise)

        section_exam_links = [
            dict(link) for link in section_spec.get("exam_links", [])
        ]
        sections.append({
            "id": section_id,
            "order": index,
            "slug": section_spec.get("slug", slugify(section_spec["title"])),
            "title": section_spec["title"],
            "est_minutes": section_spec.get("est_minutes", 10),
            "learning_objectives": [
                {"id": f"lo-{position}", "statement": objective, "bloom_level": section_spec.get("bloom_level", "understand")}
                for position, objective in enumerate(section_spec.get("objectives", []), start=1)
            ],
            "teaching_text": {"blocks": teaching},
            "worked_examples": worked,
            "misconceptions": [
                {
                    "id": f"mis-{position}",
                    "claim": rt(item["claim"]),
                    "correction": rt(item["correction"]),
                    "provenance": {
                        "publisher": spec.get("publisher", "OpenStax"),
                        "title": spec.get("source_title", spec.get("title")),
                        "url": spec.get("source_url", ""),
                        "locator": item.get("locator") or section_spec.get("locator", ""),
                        "licence": spec.get("licence", ""),
                    },
                }
                for position, item in enumerate(section_spec.get("misconceptions", []), start=1)
            ],
            "summary_points": [rt(point) for point in section_spec.get("summary", [])],
            "exercise_ids": [exercise["id"] for exercise in section_exercises],
            "exam_links": section_exam_links,
            "provenance": {
                "publisher": spec.get("publisher", "OpenStax"),
                "title": spec.get("source_title", spec.get("title")),
                "url": spec.get("source_url", ""),
                "locator": section_spec.get("locator", spec.get("source_locator", "")),
                "licence": spec.get("licence", ""),
            },
        })
        if section_spec.get("no_worked_example_reason"):
            sections[-1]["no_worked_example_reason"] = section_spec["no_worked_example_reason"]
        exercises.extend(section_exercises)

    # The chapter holds the union of its sections' exam links, so a reader of
    # the chapter sees the whole exam picture at once.
    union = {}
    for section in sections:
        for link in section.get("exam_links", []):
            key = (link.get("exam"), link.get("subject"), link.get("topic_slug"), link.get("subtopic_slug"))
            if key not in union:
                union[key] = dict(link)
    if not union and spec.get("exam_links"):
        union = {
            (link.get("exam"), link.get("subject"), link.get("topic_slug"), link.get("subtopic_slug")): dict(link)
            for link in spec["exam_links"]
        }
    chapter_links = sorted(
        union.values(),
        key=lambda link: (link.get("exam") or "", link.get("topic_slug") or "", link.get("subtopic_slug") or ""),
    )

    traps = []
    for trap in spec.get("exam_traps", []):
        traps.append({
            "id": trap["id"],
            "exam": trap["exam"],
            "subject": trap["subject"],
            "section_id": trap["section_id"],
            "misconception": rt(trap["misconception"]),
            "correction": rt(trap["correction"]),
            "signal": rt(trap["signal"]),
            "paper_evidence": trap["paper_evidence"],
            "status": trap.get("status", "proven"),
            "frequency": trap.get("frequency", "occasional"),
            "provenance": {
                "publisher": "OpenStax",
                "title": "College Physics 2e",
                "url": trap["paper_evidence"].get("url") or (
                    "https://api.utmelab.com/api/v1/chapters/"
                    f"{spec['chapter_id']}/sections/{trap['section_id']}"
                ),
                "locator": (
                    f"paper question {trap['paper_evidence']['question_id']}"
                    if trap["paper_evidence"].get("question_id")
                    else f"our practice question {trap['paper_evidence'].get('check_id')}"
                ),
                "licence": spec.get("licence", ""),
            },
        })

    recall = []
    for check in spec.get("exam_recall_checks", []):
        recall.append({
            "id": check["id"],
            "exam": check["exam"],
            "subject": check["subject"],
            "section_id": check["section_id"],
            "stem": rt(check["stem"]),
            "options": check["options"],
            "answer": check["answer"],
            "explanation": rt(check["explanation"]),
            "difficulty": check.get("difficulty", 2),
            "source": check.get("source", ""),
        })

    chapter = {
        "chapter_id": spec["chapter_id"],
        "schema_version": 2,
        "updated_at": spec.get("updated_at", "2026-11-12"),
        "title": spec["title"],
        "book_id": spec["book_id"],
        "part_id": spec.get("part_id"),
        "learning_objectives": [
            {"id": f"lo-{position}", "statement": objective, "bloom_level": spec.get("bloom_level", "understand")}
            for position, objective in enumerate(spec.get("learning_objectives", []), start=1)
        ],
        "prerequisites": spec.get("prerequisites", []),
        "formula_sheet": spec.get("formula_sheet", []),
        "glossary": spec.get("glossary", []),
        "sections": sections,
        "exercises": exercises,
        "exam_links": chapter_links,
        "exam_traps": traps,
        "exam_recall_checks": recall,
        "sources": spec.get("sources", []),
    }
    return chapter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--check", action="store_true", help="fail if the built chapter differs from the file on disk")
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    chapter = build(spec)
    target = CHAPTERS / f"{spec['chapter_id']}.json"
    rendered = json.dumps(chapter, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        current = target.read_text() if target.exists() else ""
        if current != rendered:
            print(f"{target} differs from its spec")
            raise SystemExit(1)
        print(f"{target} matches its spec")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered)
    figures = sum(
        1
        for section in chapter["sections"]
        for block in section["teaching_text"]["blocks"]
        if block["type"] == "figure"
    )
    print(
        f"wrote {target}: {len(chapter['sections'])} sections, "
        f"{len(chapter['exercises'])} exercises, {figures} figures"
    )


if __name__ == "__main__":
    main()
