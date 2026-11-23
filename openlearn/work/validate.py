#!/usr/bin/env python3
"""Validate OpenLearn records: schema v0.1 + cross-record integrity.

Usage:
    python3 openlearn/work/validate.py [dir ...]

Defaults to `openlearn/work/normalized`. Exits 1 if any error is found;
dangling references are reported as warnings because pilots may intentionally
reference Concepts whose definitions are not yet extracted.
"""

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "conventions", "schema-v0.1.json")

KNOWLEDGE_KINDS = {"Concept", "Statement", "Procedure", "Model", "Relation"}
STUDY_KINDS = {"StudyTopic", "StudyDerivation"}
EXAM_ID_RE = re.compile(r"(?:^|[:_-])(jamb|waec|neco)(?:$|[:_-])", re.IGNORECASE)

# Fields that hold references to other records.
REF_FIELDS = [
    "source_refs",
    "definition_refs",
    "linked_statements",
    "distinguished_from",
    "about",
    "provenance",
    "knowledge_refs",
    "components",
    "predictions",
]
REF_SCALARS = ["from", "to", "source_ref", "supports_relation"]


def load_records(paths):
    records = []
    for path in paths:
        if os.path.isdir(path):
            files = sorted(glob.glob(os.path.join(path, "**", "*.json"), recursive=True))
        else:
            files = [path]
        for file_path in files:
            with open(file_path, encoding="utf-8") as f:
                try:
                    record = json.load(f)
                except json.JSONDecodeError as exc:
                    records.append((file_path, None, str(exc)))
                    continue
                records.append((file_path, record, None))
    return records


def schema_validate(records, schema):
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(schema)
    defs = schema["$defs"]
    results = []
    for file_path, record, parse_error in records:
        if parse_error:
            results.append((file_path, record, [f"invalid JSON: {parse_error}"]))
            continue
        kind = record.get("kind")
        if kind not in defs:
            results.append((file_path, record, [f"unknown kind: {kind!r}"]))
            continue
        validator = Draft202012Validator({"$ref": f"#/$defs/{kind}", "$defs": defs})
        errors = sorted(validator.iter_errors(record), key=lambda e: list(e.path))
        messages = [
            f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors
        ]
        results.append((file_path, record, messages))
    return results


def collect_refs(record):
    refs = []
    for field in REF_FIELDS:
        value = record.get(field)
        if isinstance(value, list):
            refs.extend((field, item) for item in value if isinstance(item, str))
    for field in REF_SCALARS:
        value = record.get(field)
        if isinstance(value, str):
            refs.append((field, value))
    for item in record.get("items", []):
        if isinstance(item, dict) and isinstance(item.get("ref"), str):
            refs.append(("items[].ref", item["ref"]))
    for placement in record.get("placements", []):
        if isinstance(placement, dict):
            for item in placement.get("knowledge_refs", []):
                refs.append(("placements[].knowledge_refs", item))
    return refs


def main(argv):
    targets = argv[1:] or [os.path.join(ROOT, "work", "normalized")]
    schema = json.load(open(SCHEMA_PATH, encoding="utf-8"))
    records = load_records(targets)

    errors = []
    warnings = []

    # 1. Schema validation
    schema_results = schema_validate(records, schema)
    for file_path, record, messages in schema_results:
        if messages:
            errors.append((file_path, "schema", messages))

    parsed = [(p, r) for p, r, e in records if r is not None]
    by_id = {r["id"]: r for _, r in parsed if r.get("id")}

    # 2. Duplicate IDs
    ids = {}
    for file_path, record in parsed:
        rid = record.get("id")
        if rid:
            ids.setdefault(rid, []).append(file_path)
    for rid, paths in ids.items():
        if len(paths) > 1:
            errors.append((paths[0], "duplicate id", [f"{rid} also in {', '.join(paths[1:])}"]))

    # 3. Dangling references
    for file_path, record in parsed:
        for field, ref in collect_refs(record):
            if ref not in ids:
                warnings.append(
                    (file_path, "dangling ref", [f"{field} -> {ref} (not in loaded set)"])
                )

    # 3b. Reference cycles (among records in the loaded set)
    adj = {}
    for file_path, record in parsed:
        rid = record.get("id")
        if not rid:
            continue
        refs = []
        for _, ref in collect_refs(record):
            if ref in ids and ref != rid:
                refs.append(ref)
        adj[rid] = refs

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {rid: WHITE for rid in ids}
    stack = []
    cycles = []

    def canon_cycle(nodes):
        # nodes is a closed cycle [a,b,...,a]
        core = nodes[:-1]
        if not core:
            return tuple()
        m = min(range(len(core)), key=lambda i: core[i])
        rotated = core[m:] + core[:m]
        return tuple(rotated + [rotated[0]])

    seen_cycles = set()

    def dfs(u):
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            state = color.get(v, WHITE)
            if state == GRAY:
                idx = stack.index(v)
                cyc = stack[idx:] + [v]
                key = canon_cycle(cyc)
                if key and key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(cyc)
            elif state == WHITE:
                dfs(v)
        stack.pop()
        color[u] = BLACK

    for rid in sorted(ids):
        if color[rid] == WHITE:
            dfs(rid)

    if cycles:
        warnings.append(
            (targets[0] if targets else ROOT, "reference cycles", [f"{len(cycles)} cycle(s) detected in loaded records"])
        )
        for cyc in cycles[:50]:
            warnings.append(
                (targets[0] if targets else ROOT, "cycle", [" -> ".join(cyc)])
            )
        if len(cycles) > 50:
            warnings.append(
                (targets[0] if targets else ROOT, "cycle", [f"... {len(cycles) - 50} more cycle(s) omitted"])
            )

    # 4. Source refs / license presence
    sources = {r["id"]: (p, r) for p, r in parsed if r.get("kind") == "SourceAttribution"}
    for file_path, record in parsed:
        if record.get("kind") in KNOWLEDGE_KINDS | STUDY_KINDS:
            for ref in record.get("source_refs", []):
                if ref not in sources:
                    warnings.append(
                        (file_path, "unresolved source", [f"source_refs -> {ref}"])
                    )
                elif not sources[ref][1].get("license"):
                    errors.append(
                        (file_path, "missing license", [f"{ref} has no license"])
                    )
    for source_id, (file_path, record) in sources.items():
        if not record.get("license"):
            errors.append((file_path, "missing license", [f"{source_id} has no license"]))
        if not record.get("license_basis"):
            warnings.append((file_path, "missing license_basis", [source_id]))

    # 5. No exam/syllabus identifiers in Knowledge/Study records
    exam_keys = {"exam", "exams", "placements", "topic_slug", "subtopic_slug", "syllabus"}
    for file_path, record in parsed:
        if record.get("kind") not in KNOWLEDGE_KINDS | STUDY_KINDS:
            continue
        leaked = sorted(exam_keys & set(record))
        if leaked:
            errors.append(
                (file_path, "exam/syllabus leak", [f"forbidden keys: {', '.join(leaked)}"])
            )
        rid = record.get("id", "")
        if EXAM_ID_RE.search(rid):
            errors.append((file_path, "exam id in core", [rid]))

    # 6. External placements must map exam paths to core Knowledge IDs
    for file_path, record in parsed:
        if record.get("kind") != "ExternalPlacement":
            continue
        stem = os.path.splitext(os.path.basename(record.get("source_capture", "")))[0]
        if stem and stem in record.get("id", ""):
            errors.append(
                (file_path, "capture-derived external id", [f"{record['id']} embeds {stem}"])
            )
        record_refs = list(record.get("knowledge_refs", []))
        for placement in record.get("placements", []):
            record_refs.extend(placement.get("knowledge_refs", []))
        for ref in record_refs:
            target = by_id.get(ref)
            if target and target.get("kind") not in KNOWLEDGE_KINDS:
                errors.append(
                    (file_path, "external ref not core", [f"{ref} is {target.get('kind')}"])
                )

    # 7. Definition gate: a complete Concept must be fixed by a definitional Statement
    for file_path, record in parsed:
        if record.get("kind") != "Concept":
            continue
        status = record.get("definition_status")
        if status != "complete":
            warnings.append(
                (file_path, "unvetted concept", [f"definition_status: {status}"])
            )
            continue
        refs = record.get("definition_refs", [])
        if not refs:
            errors.append(
                (file_path, "definition gate", ["complete concept has no definition_refs"])
            )
        for ref in refs:
            target = by_id.get(ref)
            if target is None:
                continue  # already reported as a dangling ref
            if target.get("kind") != "Statement" or target.get("status") != "definitional":
                errors.append(
                    (
                        file_path,
                        "definition gate",
                        [f"{ref} is not a definitional Statement"],
                    )
                )
        if "definition" in record:
            warnings.append(
                (
                    file_path,
                    "embedded definition",
                    ["complete concept still embeds definition text; production requires definition_refs"],
                )
            )

    # Report
    total = len(records)
    failed_files = {p for p, _, _ in errors}
    passed = total - len(failed_files)
    print(f"records: {total}  pass: {passed}  fail: {len(failed_files)}")
    print(f"errors: {len(errors)}  warnings: {len(warnings)}")

    if errors:
        print("\nERRORS")
        for file_path, label, messages in errors:
            print(f"- {os.path.relpath(file_path)} [{label}]")
            for message in messages:
                print(f"    {message}")

    if warnings:
        print("\nWARNINGS")
        for file_path, label, messages in warnings:
            print(f"- {os.path.relpath(file_path)} [{label}]")
            for message in messages:
                print(f"    {message}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
