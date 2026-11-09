#!/usr/bin/env python3
"""Export production study notes to a local, ignored snapshot.

The live Turso DB is the source of truth; this script produces a durable
rollback copy under data/notes-snapshots/ (gitignored) plus a manifest
with per-note hashes and source counts. Re-run after every bulk import.

Usage:
    python3 scripts/export_notes.py [--out data/notes-snapshots] [--prefix YYYY-MM-DD-post-import]

Reads TURSO_DB_URL / TURSO_DB_TOKEN from .env. Never prints secrets.
"""
import argparse
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def load_env(path: Path):
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def pipeline_endpoint(url: str) -> str:
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url).split("?")[0].rstrip("/")
    base = "https://" + host
    return base if "/v2" in base else base + "/v2/pipeline"


def query(endpoint: str, token: str, sql: str):
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"type": "execute", "sql": sql}},
            {"type": "close"},
        ]
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.load(r)
    result = resp["results"][0]["response"]["result"]
    cols = [c["name"] for c in result["cols"]]
    rows = []
    for row in result["rows"]:
        out = {}
        for c, v in zip(cols, row):
            out[c] = v.get("value") if isinstance(v, dict) else v
        rows.append(out)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/notes-snapshots")
    ap.add_argument("--prefix", default=datetime.now(timezone.utc).strftime("%Y-%m-%d-post-import"))
    ap.add_argument("--env", default=".env")
    args = ap.parse_args()

    env = load_env(Path(args.env))
    url = env.get("TURSO_DB_URL", "")
    token = env.get("TURSO_DB_TOKEN", "")
    if not url or not token:
        raise SystemExit("missing TURSO_DB_URL / TURSO_DB_TOKEN in .env")
    endpoint = pipeline_endpoint(url)

    sql = (
        "SELECT id, exam, subject, topic_slug, subtopic_slug, title, "
        "read_time_minutes, key_takeaway, sections, worked_examples, "
        "formulas, active_recall_checks, examiner_traps, sources, "
        "linked_question_ids, content_hash, created_at, updated_at "
        "FROM topic_notes ORDER BY id"
    )
    rows = query(endpoint, token, sql)

    notes = []
    manifest_notes = []
    for r in rows:
        n = {
            "id": r["id"],
            "exam": r["exam"],
            "subject": r["subject"],
            "topic_slug": r["topic_slug"],
            "subtopic_slug": r["subtopic_slug"],
            "title": r["title"],
            "read_time_minutes": int(r["read_time_minutes"]),
            "key_takeaway": json.loads(r["key_takeaway"]),
            "sections": json.loads(r["sections"]),
            "worked_examples": json.loads(r["worked_examples"]),
            "formulas": json.loads(r["formulas"]),
            "active_recall_checks": json.loads(r["active_recall_checks"]),
            "examiner_traps": json.loads(r["examiner_traps"]),
            "sources": json.loads(r["sources"]),
            "linked_question_ids": json.loads(r["linked_question_ids"]),
        }
        notes.append(n)
        manifest_notes.append(
            {
                "id": r["id"],
                "placement": f"{r['exam']}/{r['subject']}/{r['topic_slug']}",
                "subtopic_slug": r["subtopic_slug"],
                "title": r["title"],
                "read_time_minutes": n["read_time_minutes"],
                "bytes": len(json.dumps(n).encode()),
                "snapshot_sha256": hashlib.sha256(
                    json.dumps(n, sort_keys=True).encode()
                ).hexdigest(),
                "db_content_hash": r["content_hash"],
                "db_created_at": r["created_at"],
                "db_updated_at": r["updated_at"],
                "sources_count": len(n["sources"]),
            }
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes_path = out_dir / f"{args.prefix}-notes.json"
    manifest_path = out_dir / f"{args.prefix}-manifest.json"
    notes_path.write_text(json.dumps(notes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = {
        "snapshot": notes_path.name,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "read-only SELECT from production Turso topic_notes",
        "note_count": len(notes),
        "notes": manifest_notes,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"exported {len(notes)} notes -> {notes_path}")
    print(f"manifest -> {manifest_path}")
    print(f"sha256: {hashlib.sha256(notes_path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
