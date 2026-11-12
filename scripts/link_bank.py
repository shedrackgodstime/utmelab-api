#!/usr/bin/env python3
"""Link the question bank to the chapters, and report the coverage.

    python3 scripts/link_bank.py

For every exam link in a chapter spec, this finds the questions in the
production bank that sit in the linked subtopic, writes their ids into the
spec, and reports what the exam side of the book actually holds.

The spec keeps the truth, so the chapter can be rebuilt without a database.
"""
import json
import os
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "data/chapter-specs"
REPORT = ROOT / "data/coverage/bank-coverage.json"
NS = {"c": "http://cnx.rice.edu/cnxml"}


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


ENV = load_env()
URL = ENV.get("TURSO_DB_URL", "")
TOKEN = ENV.get("TURSO_DB_TOKEN") or ENV.get("TURSO_DB_TOKEN_READONLY", "")
if URL.startswith("turso://"):
    URL = "https://" + URL[len("turso://"):]


def query(stmt, args=None):
    typed = [{"type": "text", "value": value} for value in (args or [])]
    body = {"requests": [{"type": "execute", "stmt": {"sql": stmt, "args": typed}}, {"type": "close"}]}
    response = requests.post(
        URL + "/v2/pipeline", json=body, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=60
    )
    response.raise_for_status()
    rows = []
    for item in response.json().get("results", []):
        if item.get("type") != "ok":
            continue
        result = item.get("response", {}).get("result")
        if not result:
            continue
        columns = [column["name"] for column in result.get("cols", [])]
        for row in result.get("rows", []):
            rows.append({column: row[index].get("value") for index, column in enumerate(columns)})
    return rows


def main():
    report = []
    for path in sorted(SPECS.glob("*.json")):
        spec = json.loads(path.read_text())
        changed = False
        for link in spec.get("exam_links", []):
            if not link.get("subtopic_slug"):
                link["question_ids"] = []
                continue
            rows = query(
                "SELECT id FROM questions WHERE exam = ? AND subject = ? AND subtopic_id = ? "
                "ORDER BY year DESC, id",
                [link["exam"], link["subject"], link["subtopic_slug"]],
            )
            ids = [row["id"] for row in rows]
            if link.get("question_ids") != ids:
                link["question_ids"] = ids
                changed = True
            report.append({
                "chapter_id": spec["chapter_id"],
                "exam": link["exam"],
                "subject": link["subject"],
                "topic_slug": link["topic_slug"],
                "subtopic_slug": link["subtopic_slug"],
                "questions": len(ids),
            })
        if changed:
            path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
            print(f"updated {path.name}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    print()
    print(f"{'chapter':<40} {'exam':<6} {'questions in the bank':>21}")
    for row in report:
        print(f"{row['chapter_id']:<40} {row['exam']:<6} {row['questions']:>21}")
    empty = [row for row in report if row["questions"] == 0 and row["subtopic_slug"]]
    print()
    print(f"links with no questions in the bank: {len(empty)} of {len(report)}")


if __name__ == "__main__":
    main()
