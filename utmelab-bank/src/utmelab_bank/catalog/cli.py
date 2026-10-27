"""Build, check and apply the WAEC catalog.

This command is the catalog owner. The bank pipeline only reads the catalog, so
the full production token stays here and never enters a batch job.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from ..adapters.database import TursoClient, prod_client
from ..config import catalog_write_credentials, load_settings
from .apply import apply_plan, plan_subject
from .model import Syllabus
from .parse import ParseError, parse
from .pdf import normalise, read_lines, text_of
from .profiles import profile_for
from .sources import Source, cache_dir, fetch, load_manifest


def repo_data_dir() -> Path:
    """Find ``data/waec`` from either the repo root or the bank crate."""
    for candidate in (Path("data/waec"), Path("../data/waec")):
        if candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError("cannot find data/waec; pass --data-dir")


def _subject_files(data_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in data_dir.glob("*.json")
        if path.name not in {"sources.json", "verifications.json"}
    )


def _metadata(data_dir: Path, slug: str) -> dict[str, Any]:
    path = data_dir / f"{slug}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    subjects = data.get("subjects") or []
    return subjects[0] if subjects else {}


def _taken_slugs(data_dir: Path, subject: str) -> set[str]:
    taken: set[str] = set()
    for path in _subject_files(data_dir):
        if path.stem == subject:
            continue
        data = json.loads(path.read_text())
        taken.update(row["slug"] for row in data.get("topics", []))
        taken.update(row["slug"] for row in data.get("subtopics", []))
    return taken


def _vocabulary(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _check_presence(syllabus: Syllabus, source_text: str) -> list[str]:
    """Every emitted word must exist in the PDF. This rejects invention.

    A two-column PDF can split a line, so a clean subtopic is not always a
    contiguous substring of the flat text. Falling back to the word set keeps
    the guarantee that matters (no new words) without failing on order.
    """
    haystack = normalise(source_text)
    vocabulary = _vocabulary(source_text)
    missing: list[str] = []
    pairs = [("topic", topic.name) for topic in syllabus.topics]
    pairs += [
        ("subtopic", subtopic.name) for topic in syllabus.topics for subtopic in topic.subtopics
    ]
    for label, name in pairs:
        if normalise(name) in haystack:
            continue
        if _vocabulary(name) <= vocabulary:
            continue
        missing.append(f"{label}: {name!r}")
    return missing


def _render(syllabus: Syllabus, limit: int) -> None:
    print(f"{syllabus.subject}: {len(syllabus.topics)} topics")
    shown = syllabus.topics if limit <= 0 else syllabus.topics[:limit]
    for topic in shown:
        print(f"  {topic.order:>2}. {topic.name}")
        for subtopic in topic.subtopics[:3]:
            print(f"        - {subtopic.name[:110]}")
        if len(topic.subtopics) > 3:
            print(f"        ... {len(topic.subtopics) - 3} more")
    if limit > 0 and len(syllabus.topics) > limit:
        print(f"  ... {len(syllabus.topics) - limit} more topics")


def _write(data_dir: Path, syllabus: Syllabus, metadata: dict[str, Any]) -> Path:
    taken = _taken_slugs(data_dir, syllabus.subject)
    topic_rows, subtopic_rows = syllabus.rows(taken=taken, hint=syllabus.subject)
    subject = {
        "slug": syllabus.subject,
        "exam": "WAEC",
        "name": metadata.get("name") or syllabus.display,
        "is_compulsory": bool(metadata.get("is_compulsory", False)),
        "objective_paper_questions": int(metadata.get("objective_paper_questions", 50)),
        "countries": metadata.get("countries", []),
        "syllabus_exam": "WAEC",
        "syllabus_subject": syllabus.subject,
    }
    path = data_dir / f"{syllabus.subject}.json"
    path.write_text(
        json.dumps(
            {"subjects": [subject], "topics": topic_rows, "subtopics": subtopic_rows},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    return path


def cmd_parse(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    manifest = load_manifest(data_dir / "sources.json")
    pdf_dir: Path = args.pdf_dir
    subjects = args.subject or ["all"]
    if "all" in subjects:
        subjects = sorted(manifest)

    failures = 0
    for slug in subjects:
        source: Source | None = manifest.get(slug)
        if source is None:
            print(f"{slug}: not in sources.json", file=sys.stderr)
            failures += 1
            continue
        try:
            pdf = fetch(source, pdf_dir / f"{slug}.pdf")
            lines = read_lines(pdf)
            profile = profile_for(slug, source.name)
            syllabus = parse(lines, profile)
            missing = _check_presence(syllabus, text_of(lines))
            if missing:
                failures += 1
                print(f"{slug}: {len(missing)} strings not found in the PDF", file=sys.stderr)
                for item in missing[:5]:
                    print(f"  {item}", file=sys.stderr)
                continue
            _render(syllabus, args.limit)
            if args.write:
                path = _write(data_dir, syllabus, _metadata(data_dir, slug))
                print(f"  wrote {path}")
        except (ParseError, ValueError, OSError) as exc:
            failures += 1
            print(f"{slug}: {exc}", file=sys.stderr)
    return 1 if failures else 0


def _load_catalog(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(path.read_text())
    subjects = data.get("subjects") or []
    return (subjects[0] if subjects else {}), data.get("topics") or [], data.get("subtopics") or []


def _name_defect(name: str) -> str | None:
    """Reject the artefacts the old HTML importer left behind."""
    if not name.strip():
        return "blank name"
    if name != name.strip():
        return "leading or trailing whitespace"
    if "  " in name:
        return "double space"
    if any(char in name for char in ("•", "∗", "\ufffd", "\xa0")):
        return "PDF artefact"
    if name.endswith(("-", "–", "—")):
        return "dangling hyphen"
    return None


def cmd_check(args: argparse.Namespace) -> int:
    """Apply the catalog contract to the JSON before any write."""
    data_dir: Path = args.data_dir
    manifest = load_manifest(data_dir / "sources.json")
    subjects = args.subject or sorted(manifest)
    errors: list[str] = []
    warnings: list[str] = []
    topic_slugs: dict[str, str] = {}
    subtopic_slugs: dict[str, str] = {}
    total_topics = 0
    total_subtopics = 0
    for slug in subjects:
        path = data_dir / f"{slug}.json"
        if not path.exists():
            errors.append(f"{slug}: no catalog file")
            continue
        subject, topics, subtopics = _load_catalog(path)
        if subject.get("slug") != slug:
            errors.append(f"{slug}: subject slug is {subject.get('slug')!r}")
        if not str(subject.get("name") or "").strip():
            errors.append(f"{slug}: subject has no name")
        local_topic_slugs = {str(row.get("slug")) for row in topics}
        seen_names: set[str] = set()
        for row in topics:
            row_slug = str(row.get("slug") or "")
            name = str(row.get("name") or "")
            if not row_slug:
                errors.append(f"{slug}: topic with no slug")
                continue
            if row_slug in topic_slugs:
                errors.append(f"{slug}/{row_slug}: duplicate topic slug")
            topic_slugs[row_slug] = slug
            defect = _name_defect(name)
            if defect:
                errors.append(f"{slug}/{row_slug}: {defect}: {name!r}")
            key = normalise(name)
            if key in seen_names:
                warnings.append(f"{slug}: duplicate topic name {name!r}")
            seen_names.add(key)
            if not any(str(sub.get("topic")) == row_slug for sub in subtopics):
                errors.append(f"{slug}/{row_slug}: topic has no subtopics")
        seen_sub_names: set[tuple[str, str]] = set()
        for row in subtopics:
            row_slug = str(row.get("slug") or "")
            name = str(row.get("name") or "")
            topic = str(row.get("topic") or "")
            if not row_slug:
                errors.append(f"{slug}: subtopic with no slug")
                continue
            if row_slug in subtopic_slugs:
                errors.append(f"{slug}/{row_slug}: duplicate subtopic slug")
            subtopic_slugs[row_slug] = slug
            defect = _name_defect(name)
            if defect:
                errors.append(f"{slug}/{row_slug}: {defect}: {name!r}")
            if topic not in local_topic_slugs:
                errors.append(f"{slug}/{row_slug}: orphan subtopic (topic {topic!r})")
            sub_key = (topic, normalise(name))
            if sub_key in seen_sub_names:
                warnings.append(f"{slug}/{row_slug}: duplicate subtopic name {name!r}")
            seen_sub_names.add(sub_key)
        total_topics += len(topics)
        total_subtopics += len(subtopics)
    print(f"checked {len(subjects)} subjects: {total_topics} topics, {total_subtopics} subtopics")
    print(f"errors: {len(errors)}")
    for item in errors[: args.limit]:
        print(f"  error: {item}")
    print(f"warnings: {len(warnings)}")
    for item in warnings[: args.limit]:
        print(f"  warning: {item}")
    if errors or (args.strict and warnings):
        return 1
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare a fresh PDF parse with the JSON now on disk. No writes."""
    data_dir: Path = args.data_dir
    manifest = load_manifest(data_dir / "sources.json")
    subjects = args.subject or sorted(manifest)
    for slug in subjects:
        source = manifest.get(slug)
        if source is None:
            print(f"{slug}: not in sources.json", file=sys.stderr)
            return 1
        path = data_dir / f"{slug}.json"
        if not path.exists():
            print(f"{slug}: no catalog file", file=sys.stderr)
            return 1
        try:
            lines = read_lines(fetch(source, args.pdf_dir / f"{slug}.pdf"))
            new = parse(lines, profile_for(slug, source.name))
        except (ParseError, ValueError, OSError) as exc:
            print(f"{slug}: {exc}", file=sys.stderr)
            return 1
        _subject, old_topics, old_subtopics = _load_catalog(path)
        old_by = {normalise(str(row.get("name") or "")): row for row in old_topics}
        new_by = {normalise(topic.name): topic for topic in new.topics}
        removed = [row for key, row in old_by.items() if key not in new_by]
        added = [topic for key, topic in new_by.items() if key not in old_by]
        new_sub_count = sum(len(topic.subtopics) for topic in new.topics)
        print(
            f"{slug}: topics {len(old_topics)} -> {len(new.topics)} "
            f"(+{len(added)} -{len(removed)}), "
            f"subtopics {len(old_subtopics)} -> {new_sub_count}"
        )
        for row in removed[: args.limit]:
            print(f"  - topic {row.get('name')!r}")
        for topic in added[: args.limit]:
            print(f"  + topic {topic.name!r}")
        for key in sorted(old_by.keys() & new_by.keys()):
            old_subs = {
                normalise(str(row.get("name") or ""))
                for row in old_subtopics
                if str(row.get("topic")) == old_by[key].get("slug")
            }
            new_subs = {normalise(sub.name) for sub in new_by[key].subtopics}
            lost = old_subs - new_subs
            if lost:
                print(f"  - {len(lost)} subtopic(s) under {old_by[key].get('name')!r}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Reseed production from the built JSON. Dry run unless ``--apply``."""
    return asyncio.run(_apply(args))


async def _apply(args: argparse.Namespace) -> int:
    data_dir: Path = args.data_dir
    subjects = args.subject or ["all"]
    if "all" in subjects:
        subjects = [path.stem for path in _subject_files(data_dir)]

    if args.apply:
        url, token = catalog_write_credentials()
        client = TursoClient(url, token)
    else:
        client = prod_client(load_settings())

    failures = 0
    try:
        for slug in subjects:
            path = data_dir / f"{slug}.json"
            if not path.exists():
                print(f"{slug}: no catalog file", file=sys.stderr)
                failures += 1
                continue
            try:
                plan = await plan_subject(client, json.loads(path.read_text()), slug)
            except Exception as exc:  # noqa: BLE001 - report the subject and continue
                print(f"{slug}: {exc}", file=sys.stderr)
                failures += 1
                continue
            print(plan.summary())
            for topic in plan.topics[: args.limit]:
                print(f"  + topic {topic['name']!r}")
            for slug_to_delete in plan.delete_topics[: args.limit]:
                print(f"  - topic {slug_to_delete!r}")
            if plan.kept_referenced:
                print(f"  kept referenced: {', '.join(plan.kept_referenced[: args.limit])}")
            if args.apply:
                try:
                    await apply_plan(client, plan)
                except Exception as exc:  # noqa: BLE001 - one subject at a time
                    print(f"{slug}: apply failed: {exc}", file=sys.stderr)
                    failures += 1
                    continue
                print(f"  applied {slug}")
    finally:
        await client.close()
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="utmelab-catalog",
        description="Build and check the WAEC catalog from the pinned PDFs.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="the data/waec directory (default: discover it)",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=None,
        help="where the pinned PDFs are cached (default: user cache)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    parse_cmd = sub.add_parser("parse", help="rebuild subject JSON from the PDFs")
    parse_cmd.add_argument("subject", nargs="*", help="subject slugs; default: all")
    parse_cmd.add_argument("--write", action="store_true", help="replace the subject JSON")
    parse_cmd.add_argument("--limit", type=int, default=0, help="print at most N topics each")
    parse_cmd.set_defaults(handler=cmd_parse)

    check_cmd = sub.add_parser("check", help="apply the catalog contract to the JSON")
    check_cmd.add_argument("subject", nargs="*", help="subject slugs; default: all")
    check_cmd.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings (duplicate names) as failures",
    )
    check_cmd.add_argument("--limit", type=int, default=20, help="print at most N findings each")
    check_cmd.set_defaults(handler=cmd_check)

    diff_cmd = sub.add_parser("diff", help="compare a fresh parse with the JSON on disk")
    diff_cmd.add_argument("subject", nargs="*", help="subject slugs; default: all")
    diff_cmd.add_argument("--limit", type=int, default=10, help="print at most N changes each")
    diff_cmd.set_defaults(handler=cmd_diff)

    apply_cmd = sub.add_parser("apply", help="reseed production from the JSON; dry run by default")
    apply_cmd.add_argument("subject", nargs="*", help="subject slugs; default: all")
    apply_cmd.add_argument("--apply", action="store_true", help="write the plan (default: dry run)")
    apply_cmd.add_argument(
        "--limit", type=int, default=5, help="print at most N sample topics each"
    )
    apply_cmd.set_defaults(handler=cmd_apply)

    args = parser.parse_args(argv)
    if args.data_dir is None:
        args.data_dir = repo_data_dir()
    if args.pdf_dir is None:
        args.pdf_dir = cache_dir()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
