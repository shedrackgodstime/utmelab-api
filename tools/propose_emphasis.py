#!/usr/bin/env python3
"""Emphasis backfill worksheet — propose and apply, never guess.

The 78 underline rows need `emphasis` (the exact substring to underline) and
only a human knows which word it is. This script does the machine half:

  propose   read data/questions.json, print a TSV worksheet to stdout:
            id | sentence | candidates | options | answer
            `sentence` is the stem minus its instruction clause; `candidates`
            are the content words worth glancing at. The human reads the row
            and writes the chosen word/phrase into the `emphasis` column.

  apply     read a filled worksheet (id<TAB>emphasis per line, header
            allowed), verify every value is a non-empty substring of its stem
            (the same rule the loader enforces), write data/questions.json.

Usage:
  python3 tools/propose_emphasis.py propose > /tmp/emphasis.tsv
  # ... fill the emphasis column ...
  python3 tools/propose_emphasis.py apply /tmp/emphasis.tsv

Nothing is written by `propose`. `apply` refuses the whole file on the first
bad value rather than writing half a backfill.
"""

import json
import re
import sys

BANK = "data/questions.json"

INSTRUCTION = re.compile(
    r"^(choose\s+(the\s+)?(word|option(s)?|one)\b[^:]*:"
    r"|which\s+[^:]*underlined[^:]*:"
    r"|the\s+[^:]*underlined[^:]*:\s*)",
    re.IGNORECASE,
)

STOPWORDS = set(
    "the a an of to in is are was were be been being on for with by from as at "
    "it its this that these those and or but not no which what when where who "
    "whom whose how do does did have has had will would can could shall should "
    "may might must his her their our your my mine his hers ours yours their "
    "he she they we you i me him her us them him her above below following "
    "sentence passage option options word words underlined italics bold"
    .split()
)


def sentence_of(stem):
    """The stem minus its instruction clause — where the target lives."""
    s = " ".join(stem.split())
    m = INSTRUCTION.match(s)
    return s[m.end():].strip() if m else s


def candidates(sentence):
    """Content words, longest first — the target is usually distinctive."""
    words = re.findall(r"[A-Za-z][A-Za-z'/-]*", sentence)
    seen, out = set(), []
    for w in words:
        lw = w.lower().strip("'")
        if len(lw) > 3 and lw not in STOPWORDS and lw not in seen:
            seen.add(lw)
            out.append(w)
    return sorted(out, key=lambda w: (-len(w), w.lower()))[:8]


def propose():
    bank = json.load(open(BANK))
    rows = [
        q for q in bank
        if q.get("emphasis") is None and "underlin" in q["text"].lower()
    ]
    print("id\tsentence\tcandidates\toptions\tanswer\temphasis")
    for q in rows:
        s = sentence_of(q["text"])
        opts = " / ".join(
            f"{o['id']}:{o['text'][:40]}" for o in q["options"]
        )
        print("\t".join([
            q["id"],
            s[:220],
            ", ".join(candidates(s)),
            opts[:220],
            q["answer"],
            "",
        ]))
    print(f"# {len(rows)} rows need emphasis", file=sys.stderr)


def apply(path):
    bank = json.load(open(BANK))
    by_id = {q["id"]: q for q in bank}
    wanted = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line.startswith("id\t"):
                continue
            parts = line.split("\t")
            if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
                continue
            wanted[parts[0].strip()] = parts[1].strip()
    if not wanted:
        print("nothing to apply — the emphasis column is empty", file=sys.stderr)
        sys.exit(1)
    problems = []
    for qid, value in wanted.items():
        q = by_id.get(qid)
        if q is None:
            problems.append(f"{qid}: no such question")
        elif not value or value not in q["text"]:
            problems.append(f"{qid}: {value!r} is not a substring of its stem")
    if problems:
        print("refusing to write:", file=sys.stderr)
        for p in problems[:10]:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)
    for qid, value in wanted.items():
        by_id[qid]["emphasis"] = value
    json.dump(bank, open(BANK, "w"), indent=2, ensure_ascii=False)
    open(BANK, "a").write("\n")
    print(f"applied emphasis to {len(wanted)} rows", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("propose", "apply"):
        sys.exit("usage: propose_emphasis.py propose | apply <worksheet.tsv>")
    if sys.argv[1] == "propose":
        propose()
    else:
        if len(sys.argv) < 3:
            sys.exit("usage: propose_emphasis.py apply <worksheet.tsv>")
        apply(sys.argv[2])
