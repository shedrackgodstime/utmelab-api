#!/usr/bin/env python3
"""Assemble the exam packs.

    python3 scripts/build_packs.py

A pack is what a candidate opens for one exam, one subject and one topic. It
holds the chapters that teach the topic, the sections that cover it, the
traps the exam has shown, the recall checks written for that exam, the
chapter exercises, and the past papers the bank holds for the subtopic.

The pack also reports what it does not have. A thin pack is honest, not
empty: the gaps are the work list.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAPTERS = ROOT / "data/chapters"
PACKS = ROOT / "data/packs"


def main():
    packs = defaultdict(lambda: {
        "exam": "",
        "subject": "",
        "topic_slug": "",
        "topic_name": "",
        "subtopic_slugs": [],
        "sections": [],
        "traps": [],
        "recall_checks": [],
        "exercises": [],
        "past_papers": [],
    })

    for path in sorted(CHAPTERS.glob("*.json")):
        chapter = json.loads(path.read_text())
        for section in chapter["sections"]:
            for link in section.get("exam_links", []):
                key = (link["exam"], link["subject"], link["topic_slug"])
                pack = packs[key]
                pack["exam"] = link["exam"]
                pack["subject"] = link["subject"]
                pack["topic_slug"] = link["topic_slug"]
                if link["subtopic_slug"] not in pack["subtopic_slugs"]:
                    pack["subtopic_slugs"].append(link["subtopic_slug"])
                pack["sections"].append({
                    "chapter_id": chapter["chapter_id"],
                    "chapter_title": chapter["title"],
                    "section_id": section["id"],
                    "title": section["title"],
                    "est_minutes": section["est_minutes"],
                    "learning_objectives": [
                        objective["statement"] for objective in section.get("learning_objectives", [])
                    ],
                    "subtopic_slug": link["subtopic_slug"],
                })
                pack["exercises"].extend(section.get("exercise_ids", []))
                for paper in link.get("papers", []):
                    pack["past_papers"].append({
                        **paper,
                        "exam": link["exam"],
                        "subject": link["subject"],
                        "subtopic_slug": link["subtopic_slug"],
                    })

        for trap in chapter.get("exam_traps", []):
            key = (trap["exam"], trap["subject"], None)
            for section in chapter["sections"]:
                if section["id"] != trap["section_id"]:
                    continue
                for link in section.get("exam_links", []):
                    if link["exam"] != trap["exam"]:
                        continue
                    pack = packs[(link["exam"], link["subject"], link["topic_slug"])]
                    pack["traps"].append({
                        "id": f"{chapter['chapter_id']}:{trap['id']}",
                        "chapter_id": chapter["chapter_id"],
                        "status": trap.get("status", "proven"),
                        "section_id": trap["section_id"],
                        "misconception": trap["misconception"],
                        "correction": trap["correction"],
                        "signal": trap["signal"],
                        "paper_evidence": trap["paper_evidence"],
                        "frequency": trap.get("frequency"),
                    })
        for check in chapter.get("exam_recall_checks", []):
            for section in chapter["sections"]:
                if section["id"] != check["section_id"]:
                    continue
                for link in section.get("exam_links", []):
                    if link["exam"] != check["exam"]:
                        continue
                    pack = packs[(link["exam"], link["subject"], link["topic_slug"])]
                    pack["recall_checks"].append({
                        "id": f"{chapter['chapter_id']}:{check['id']}",
                        "chapter_id": chapter["chapter_id"],
                        "section_id": check["section_id"],
                        "stem": check["stem"],
                        "options": check["options"],
                        "answer": check["answer"],
                        "explanation": check["explanation"],
                        "difficulty": check.get("difficulty"),
                    })

    PACKS.mkdir(parents=True, exist_ok=True)
    for key, pack in sorted(packs.items()):
        pack["sections"] = sorted(pack["sections"], key=lambda item: (item["chapter_id"], item["section_id"]))
        pack["exercises"] = sorted(set(pack["exercises"]))
        unique = {}
        for paper in pack["past_papers"]:
            unique.setdefault(paper["question_id"], paper)
        pack["past_papers"] = sorted(
            unique.values(),
            key=lambda paper: (-(paper.get("year") or 0), paper.get("question_id") or ""),
        )
        claimed = sum(1 for paper in pack["past_papers"] if paper.get("source") == "claimed_paper")
        pack["paper_note"] = (
            f"{claimed} of {len(pack['past_papers'])} papers are self-published claims, "
            "labelled as such, and the rest are confirmed."
            if pack["past_papers"] else
            "No past paper for this topic yet."
        )
        pack["subtopic_slugs"] = sorted(pack["subtopic_slugs"])
        pack["coverage"] = {
            "sections": len(pack["sections"]),
            "traps": len(pack["traps"]),
            "recall_checks": len(pack["recall_checks"]),
            "exercises": len(pack["exercises"]),
            "past_papers": len(pack["past_papers"]),
            "gaps": [
                name for name, value in (
                    ("traps", len(pack["traps"])),
                    ("recall_checks", len(pack["recall_checks"])),
                    ("past_papers", len(pack["past_papers"])),
                ) if value == 0
            ],
        }
        name = f"{pack['exam']}_{pack['subject']}_{pack['topic_slug']}.json".replace("/", "-")
        path = PACKS / name
        path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
        print(
            f"{name:<58} sections={pack['coverage']['sections']} "
            f"traps={pack['coverage']['traps']} recall={pack['coverage']['recall_checks']} "
            f"exercises={pack['coverage']['exercises']} papers={pack['coverage']['past_papers']} "
            f"gaps={','.join(pack['coverage']['gaps']) or 'none'}"
        )


if __name__ == "__main__":
    main()
