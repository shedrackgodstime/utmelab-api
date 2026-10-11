#!/usr/bin/env python3
"""Review one question at a time — the review workbench.

Bash one-liners do not scale to 2,000 sittings, and review must work
identically for a human on a phone and any AI agent on any machine. No
toolchain needed: plain Python 3, standard library only.

    python3 tools/review.py show <id> [--json]
    python3 tools/review.py next [--subject <slug>] [--json]
    python3 tools/review.py verify <id>
    python3 tools/review.py set <id> [--subtopic S] [--emphasis E]
        [--section S] [--marks M] [--difficulty D] [--passage P]
    python3 tools/review.py stats

Two rules keep reviewers honest without a lock file (review happens from
several machines — shared mutable state would be the next bug):

1. Deterministic order: `next` is always the lowest-id unverified row in
   scope. No cursor, nothing to sync, resume anywhere.
2. Mechanical half enforced: `verify` refuses quarantined rows and rows with
   no explanation — the machine checks what it can (D45).

Writes back up questions.json to tmp/ first, refuse bad values before
anything writes, and re-read the file after writing. The Rust loader stays
the final gate at boot/test.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(REPO, "data")
SIBLING_CAP = 8


def die(msg):
    print(f"fatal: {msg}", file=sys.stderr)
    sys.exit(1)


def load(data):
    def read(name):
        with open(os.path.join(data, name)) as f:
            return json.load(f)

    return {
        "questions": read("questions.json"),
        "subjects": read("subjects.json"),
        "topics": read("topics.json"),
        "subtopics": read("subtopics.json"),
        "passages": read("passages.json"),
    }


def fingerprint(text, options):
    all_o = sorted(o.strip().lower() for o in options)
    joined = text.strip().lower() + "|" + "~".join(all_o)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


FIGURE_HINTS = ("diagram", "figure", "graph", "illustrat", "shown", "sketch", "table")


def flags_for(bank, q):
    """Quarantine kinds for one row — same rules as src/quarantine.rs."""
    flags = []
    text = q["text"]
    lower = text.lower()
    if q.get("emphasis") is None and "underlin" in lower:
        flags.append("underline_missing")
    if q.get("image") is None and any(h in lower for h in FIGURE_HINTS):
        flags.append("missing_figure")
    if len(q["options"]) != 4:
        flags.append("option_count")
    blob = (text + " " + " ".join(o["text"] for o in q["options"])).lower()
    if "bepo" in blob or "stardom" in blob or "lekki" in blob:
        flags.append("novel_leak")
    if q.get("passage_id") is None and has_numbered_gap(text):
        flags.append("cloze_without_passage")
    return flags


def has_numbered_gap(text):
    lower = text.lower()
    for marker in ("gap labelled", "gap numbered", "gaps labelled", "gaps numbered"):
        rest = lower
        while marker in rest:
            rest = rest.split(marker, 1)[1]
            stripped = rest.strip()
            i = 0
            while i < len(stripped) and stripped[i].isdigit():
                i += 1
            if i > 0:
                return True
    return False


def all_flags(bank):
    """Every (kind, id) pair — duplicate_stems needs the whole bank."""
    out = []
    seen = {}
    for q in sorted(bank["questions"], key=lambda r: r["id"]):
        for kind in flags_for(bank, q):
            out.append((kind, q["id"]))
        fp = fingerprint(q["text"], [o["text"] for o in q["options"]])
        if fp in seen:
            out.append(("duplicate_stem", q["id"]))
        else:
            seen[fp] = q["id"]
    return out


def bundle(bank, qid):
    by_id = {q["id"]: q for q in bank["questions"]}
    q = by_id.get(qid)
    if q is None:
        die(f"No question with id '{qid}'.")
    subject = next(
        (s for s in bank["subjects"] if s["exam"] == q["exam"] and s["slug"] == q["subject"]),
        None,
    )
    chain = []
    if q.get("subtopic_id"):
        st = next((s for s in bank["subtopics"] if s["slug"] == q["subtopic_id"]), None)
        if st:
            chain.append({"level": "subtopic", "slug": st["slug"], "name": st["name"],
                          "objectives": st.get("objectives", [])})
            t = next((t for t in bank["topics"] if t["slug"] == st["topic"]), None)
            if t:
                chain.append({"level": "topic", "slug": t["slug"], "name": t["name"],
                              "objectives": t.get("objectives", [])})
    passage = None
    if q.get("passage_id"):
        passage = next((p for p in bank["passages"] if p["id"] == q["passage_id"]), None)

    def sibling_of(o):
        if q.get("subtopic_id") and o.get("subtopic_id"):
            return o["subtopic_id"] == q["subtopic_id"]
        return o["exam"] == q["exam"] and o["subject"] == q["subject"]

    sibs = sorted(
        ({"id": o["id"], "verified": o["verified"], "text": trunc(o["text"], 90)}
         for o in bank["questions"] if o["id"] != qid and sibling_of(o)),
        key=lambda s: s["id"],
    )[:SIBLING_CAP]
    queue = sorted(o["id"] for o in bank["questions"] if not o["verified"])
    return {
        "question": q,
        "subject": subject,
        "topic_chain": chain,
        "passage": passage,
        "siblings": sibs,
        "flags": [k for k, i in all_flags(bank) if i == qid],
        "queue_position": queue.index(qid) + 1 if qid in queue else None,
    }


def trunc(text, maxn):
    return text if len(text) <= maxn else text[:maxn] + "…"


def render_human(b):
    q = b["question"]
    L = []
    L.append(f"{q['id']}  [{q['exam']}/{q['subject']}]  {'verified' if q['verified'] else 'unverified'}")
    L.append(f"source={q['source']} year={q['year']} marks={q['marks']} difficulty={q['difficulty']}"
             + (f"  queue=#{b['queue_position']}" if b["queue_position"] else ""))
    if b["subject"]:
        s = b["subject"]
        L.append(f"subject: {s['name']} (full paper: {s['full_exam_questions']}, compulsory: {s['is_compulsory']})")
    L.append("")
    L.append(q["text"])
    if q.get("emphasis"):
        L.append(f">>> underline: {q['emphasis']}")
    for i, o in enumerate(q["options"]):
        L.append(f"  {chr(ord('A') + i)}) {o['text']}")
    L.append(f"answer: {q['answer']}")
    e = q.get("explanation")
    if e:
        L.append(f"key point: {e['key_point']}\nbody:\n{e['body']}")
        if e.get("trap"):
            L.append(f"trap: {e['trap']}")
    else:
        L.append("explanation: — none —")
    if q.get("image"):
        L.append(f"image: {q['image']['url']} ({q['image']['position']})")
    for n in b["topic_chain"]:
        L.append(f"{n['level']}: {n['slug']} — {n['name']}")
        for o in n["objectives"]:
            L.append(f"    • {o}")
    if b["passage"]:
        L.append(f"--- passage {b['passage']['id']} ---\n{b['passage']['text']}\n--- end ---")
    if b["flags"]:
        L.append(f"FLAGS (verify refuses): {', '.join(b['flags'])}")
    if b["siblings"]:
        L.append("siblings:")
        for s in b["siblings"]:
            L.append(f"  {s['id']} [{'v' if s['verified'] else ' '}] {s['text']}")
    return "\n".join(L) + "\n"


def write_bank(data, bank):
    tmp = os.path.join(REPO, "tmp")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(data, "questions.json")
    shutil.copy(path, os.path.join(tmp, "questions.backup.json"))
    with open(path, "w") as f:
        json.dump(bank["questions"], f, indent=2, ensure_ascii=False)
        f.write("\n")
    # Re-read: a write we cannot parse back is rolled back, not shipped.
    try:
        json.load(open(path))
    except Exception as exc:
        shutil.copy(os.path.join(tmp, "questions.backup.json"), path)
        die(f"write failed validation ({exc}) — restored backup")


def cmd_show(args):
    bank = load(args.data)
    b = bundle(bank, args.id)
    if args.json:
        print(json.dumps(b, indent=2, ensure_ascii=False))
    else:
        print(render_human(b), end="")


def cmd_next(args):
    bank = load(args.data)
    ids = sorted(q["id"] for q in bank["questions"]
                 if not q["verified"] and (args.subject is None or q["subject"] == args.subject))
    if not ids:
        die("No unverified questions in scope.")
    b = bundle(bank, ids[0])
    if args.json:
        print(json.dumps(b, indent=2, ensure_ascii=False))
    else:
        print(render_human(b), end="")


def cmd_verify(args):
    bank = load(args.data)
    b = bundle(bank, args.id)
    if b["question"]["verified"]:
        print(f"{args.id} already verified")
        return
    if b["flags"]:
        die(f"Resolve first: {', '.join(b['flags'])}")
    if not b["question"].get("explanation"):
        die("Verified claims the working was checked — write the explanation first.")
    b["question"]["verified"] = True
    write_bank(args.data, bank)
    print(f"verified {args.id}")


def cmd_set(args):
    bank = load(args.data)
    b = bundle(bank, args.id)
    q = b["question"]
    if args.subtopic:
        # The slug must exist and its topic must belong to this exam+subject.
        subs = {s["slug"]: s for s in bank["subtopics"]}
        st = subs.get(args.subtopic)
        tops = {(t["exam"], t["subject"], t["slug"]) for t in bank["topics"]}
        if st is None or (q["exam"], q["subject"], st["topic"]) not in tops:
            die(f"No subtopic '{args.subtopic}' under {q['exam']}/{q['subject']} — tag what exists.")
        q["subtopic_id"] = args.subtopic
    if args.emphasis is not None:
        if not args.emphasis or args.emphasis not in q["text"]:
            die("Emphasis must be a non-empty substring of the stem.")
        q["emphasis"] = args.emphasis
    if args.section is not None:
        q["section"] = args.section
    if args.marks is not None:
        if not 0.5 <= args.marks <= 10.0:
            die("Marks look wrong — JAMB rows carry 1.0–3.0.")
        q["marks"] = args.marks
    if args.difficulty is not None:
        if args.difficulty not in (1, 2, 3, 4, 5):
            die("Difficulty is 1–5.")
        q["difficulty"] = args.difficulty
    if args.passage is not None:
        if args.passage not in {p["id"] for p in bank["passages"]}:
            die(f"No passage '{args.passage}'.")
        q["passage_id"] = args.passage
    write_bank(args.data, bank)
    print(f"updated {args.id}")


def cmd_stats(args):
    bank = load(args.data)
    flagged = {i for _, i in all_flags(bank)}
    rows = {}
    for q in bank["questions"]:
        rows.setdefault(q["subject"], []).append(q)
    print(f"{'SUBJECT':32} {'TOTAL':>6} {'VERIFIED':>8} {'QUARANTINED':>11}")
    for subject in sorted(rows):
        rs = rows[subject]
        print(f"{subject:32} {len(rs):>6} "
              f"{sum(1 for q in rs if q['verified']):>8} "
              f"{sum(1 for q in rs if q['id'] in flagged):>11}")


def main():
    ap = argparse.ArgumentParser(prog="review.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default=DEFAULT_DATA, help="directory holding questions.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("show", help="one question with everything related")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("next", help="lowest-id unverified row in scope")
    p.add_argument("--subject", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("verify", help="mark verified (refuses quarantined/explanationless)")
    p.add_argument("id")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("set", help="scalar edits, validated before writing")
    p.add_argument("id")
    p.add_argument("--subtopic", default=None)
    p.add_argument("--emphasis", default=None)
    p.add_argument("--section", default=None)
    p.add_argument("--marks", type=float, default=None)
    p.add_argument("--difficulty", type=int, default=None)
    p.add_argument("--passage", default=None)
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("stats", help="progress per subject")
    p.set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
