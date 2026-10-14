"""Command-line entry point for the auto-tagging SDK."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from .bank import filter_questions, get_subject_subtopics, get_subject_topics, load_bank
from .providers import build_provider
from .runner import run, summarize


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="utmetag",
        description="Auto-tag JAMB/WAEC questions with subtopics and underline marks",
    )
    p.add_argument("--subject", help="Subject to process (e.g., mathematics)")
    p.add_argument("--exam", default="JAMB", help="Exam code")
    p.add_argument("--limit", type=int, default=10, help="Max questions to process")
    p.add_argument("--data-dir", default="data", help="Data directory")
    p.add_argument(
        "--engine", default="opencode", choices=["opencode", "mock"],
        help="Provider backend: 'opencode' CLI free models (default, the only model); "
             "'mock' no network I/O (tests)",
    )
    p.add_argument("--model", default=None, help="Model id (default: opencode/space-bunny-free)")
    p.add_argument("--output", default="tagging_results.json", help="Output file path")
    p.add_argument("--all", action="store_true", help="Include already-verified questions")
    p.add_argument("--question-id", action="append", dest="question_ids", help="Only these id(s); repeatable")
    p.add_argument("--concurrency", type=int, default=3, help="Parallel requests")
    p.add_argument("--opencode-bin", default="opencode", help="Path to the opencode CLI binary")
    p.add_argument("--opencode-timeout", type=float, default=180.0, help="Per-question opencode timeout (s)")
    p.add_argument("--mock", action="store_true", help="Alias for --engine mock")
    return p


async def _run(args: argparse.Namespace) -> int:
    engine = "mock" if args.mock else args.engine

    provider = build_provider(
        engine,
        model=args.model,
        opencode_bin=args.opencode_bin,
        opencode_timeout=args.opencode_timeout,
    )
    concurrency = args.concurrency
    print(f"Engine: {engine} (provider={provider.name})")

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: Data directory not found: {data_dir}", file=sys.stderr)
        return 1

    print(f"Loading bank from {data_dir}...")
    bank = load_bank(data_dir)

    print(f"Filtering: exam={args.exam}, subject={args.subject or 'all'}, limit={args.limit}")
    questions = filter_questions(
        bank, args.subject, args.exam, args.limit,
        only_unverified=not args.all, question_ids=args.question_ids,
    )
    if not questions:
        print("No questions to process")
        return 0
    print(f"Found {len(questions)} questions to process")

    subtopics = get_subject_subtopics(bank, args.exam, args.subject) if args.subject else []
    topics = get_subject_topics(bank, args.exam, args.subject) if args.subject else []
    print(f"Available subtopics: {len(subtopics)}, topics: {len(topics)}")

    print(f"Processing {len(questions)} questions with concurrency={concurrency}...")
    start = time.time()
    try:
        results = await run(provider, questions, subtopics, topics, concurrency=concurrency)
    finally:
        await provider.aclose()
    elapsed = time.time() - start

    summary = summarize(results, elapsed)
    output = {
        "metadata": {
            "exam": args.exam,
            "subject": args.subject,
            "engine": engine,
            "model": provider.name,
            "processed": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "results": [r.to_dict() for r in results],
        "summary": summary,
    }

    Path(args.output).write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nResults written to {args.output}")
    print(f"Summary: {summary}")

    print("\n--- Sample Results ---")
    for r in results[:3]:
        if r.error:
            print(f"  {r.question_id}: ERROR - {r.error}")
        else:
            print(
                f"  {r.question_id}: subtopic={r.assigned_subtopic}, underline={r.underline_word}, "
                f"answer_ok={r.answer_verified}, quality={r.explanation_quality}, conf={r.confidence:.2f}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
