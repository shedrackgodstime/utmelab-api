#!/usr/bin/env python3
"""Normalize openlearn pilot records to schema v0.1 vocabulary.

Reads `openlearn/work/pilot-00*/` and writes normalized copies to
`openlearn/work/normalized/pilot-00*/`. Originals are never modified.

Mappings applied:
  basis: as-stated -> stated
         as-stated ... inferred ... -> mixed
         as-stated/condensed (in fidelity fields) -> paraphrased
         not extractable from this capture -> not-extractable
  fidelity / source_fidelity: same as above
  definition_fidelity -> definition_status
         as-stated -> complete
         as-stated/condensed -> complete (definition is condensed; note added)
         not extractable from this capture -> not_extractable
  status: derived/proved -> derived (and role: theorem)
  direction: symmetric-or-unspecified -> unspecified
"""

import copy
import glob
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PILOTS = ["pilot-001-newton", "pilot-002-economics", "pilot-003-math-proof"]
OUT_ROOT = os.path.join(ROOT, "normalized")

# Values that are not resolvable by a generic rule.
BASIS_MAP = {
    "as-stated": "stated",
    "as-stated for ceteris paribus; broader scope inferred": "mixed",
    "as-stated (ceteris paribus) / inferred (single-market framing)": "mixed",
    "as-stated/inferred from adjustment narrative": "mixed",
    "as-stated for continuity/definition; broader calculus scope inferred": "mixed",
    "as-stated for continuity conditions; broader calculus scope inferred": "mixed",
    "as-stated for continuity/antiderivative; broader calculus scope inferred": "mixed",
    "not extractable from this capture": "not_extractable",
}

FIDELITY_MAP = {
    "as-stated": "as-stated",
    "as-stated/condensed": "paraphrased",
    "not extractable from this capture": "not-extractable",
}

DEFINITION_STATUS_MAP = {
    "as-stated": "complete",
    "as-stated/condensed": "complete",
    "not extractable from this capture": "not_extractable",
}

# Concept anchors whose "definition" is constituted by an existing Statement.
DEFINITION_REFS = {
    "concept:newtons-second-law": ["statement:newtons-second-law"],
}


def normalize_scope(scope):
    if not isinstance(scope, dict):
        return
    if "basis" in scope:
        scope["basis"] = BASIS_MAP.get(scope["basis"], scope["basis"])
    for assumption in scope.get("conditions", []):
        if isinstance(assumption, dict) and "basis" in assumption:
            assumption["basis"] = BASIS_MAP.get(assumption["basis"], assumption["basis"])


def normalize(record):
    rec = copy.deepcopy(record)

    normalize_scope(rec.get("scope"))

    if rec.get("kind") == "Model":
        for assumption in rec.get("assumptions", []):
            if "basis" in assumption:
                assumption["basis"] = BASIS_MAP.get(assumption["basis"], assumption["basis"])

    if "definition_fidelity" in rec:
        value = rec.pop("definition_fidelity")
        rec["definition_status"] = DEFINITION_STATUS_MAP.get(value, value)

    if rec.get("status") == "derived/proved":
        rec["status"] = "derived"
        rec.setdefault("role", "theorem")

    if "fidelity" in rec:
        rec["fidelity"] = FIDELITY_MAP.get(rec["fidelity"], rec["fidelity"])
    if "source_fidelity" in rec:
        rec["source_fidelity"] = FIDELITY_MAP.get(rec["source_fidelity"], rec["source_fidelity"])

    if rec.get("direction") == "symmetric-or-unspecified":
        rec["direction"] = "unspecified"

    if rec.get("kind") == "SourceFidelity":
        for item in rec.get("items", []):
            item["fidelity"] = FIDELITY_MAP.get(item["fidelity"], item["fidelity"])

    if rec.get("kind") == "Concept":
        refs = DEFINITION_REFS.get(rec.get("id"))
        if refs and "definition_refs" not in rec:
            rec["definition_refs"] = refs
            rec["definition_status"] = "complete"
            note = (
                "Definition anchor: the named law is constituted by its linked Statement; "
                "no separate definitional Statement was extracted for this pilot."
            )
            rec["notes"] = (rec.get("notes", "") + " " + note).strip()

    return rec


def main():
    for pilot in PILOTS:
        src_dir = os.path.join(ROOT, pilot)
        out_dir = os.path.join(OUT_ROOT, pilot)
        os.makedirs(out_dir, exist_ok=True)
        for path in sorted(glob.glob(os.path.join(src_dir, "*.json"))):
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
            normalized = normalize(record)
            out_path = os.path.join(out_dir, os.path.basename(path))
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(normalized, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print("wrote", os.path.relpath(out_path, ROOT))


if __name__ == "__main__":
    main()
