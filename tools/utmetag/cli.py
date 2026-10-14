"""Command-line entry point for the auto-tagging SDK."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from .bank import filter_questions, get_subject_subtopics, get_subject_topics, load_bank
from .providers import build_provider_with_cap
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
        "--engine", default="opencode", choices=["opencode", "http", "mock"],
        help="Provider backend: 'opencode' CLI free models (default); "
             "'http' OpenAI-compatible endpoint; 'mock' no network I/O",
    )
    p.add_argument("--model", default=None, help="Model id (engine-specific default if omitted)")
    p.add_argument("--base-url", default=None, help="HTTP engine: API base URL")
    p.add_argument(
        "--provider", default="auto", choices=["auto", "pollinations", "openai"],
        help="HTTP engine provider; 'auto' prefers OPENAI_API_KEY, else free Pollinations",
    )
    p.add_argument("--output", default="tagging_results.json", help="Output file path")
    p.add_argument("--no-api-key", action="store_true", help="HTTP engine: force the no-key provider")
    p.add_argument("--all", action="store_true", help="Include already-verified questions")
    p.add_argument("--question-id", action="append", dest="question_ids", help="Only these id(s); repeatable")
    p.add_argument("--concurrency", type=int, default=3, help="Parallel requests")
    p.add_argument("--rate-limit-sec", type=float, default=None, help="HTTP engine: min seconds between requests")
    p.add_argument("--opencode-bin", default="opencode", help="Path to the opencode CLI binary")
    p.add_argument("--opencode-timeout", type=float, default=180.0, help="Per-question opencode timeout (s)")
    p.add_argument("--mock", action="store_true", help="Alias for --engine mock")
    return p


async def _run(args: argparse.Namespace) -> int:
    engine = "mock" if args.mock else args.engine

    try:
        provider, cap = build_provider_with_cap(
            engine,
            model=args.model,
            opencode_bin=args.opencode_bin,
            opencode_timeout=args.opencode_timeout,
            http_provider=args.provider,
            base_url=args.base_url,
            no_api_key=args.no_api_key,
            rate_limit_sec=args.rate_limit_sec,
        )
    except SystemExit as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    concurrency = args.concurrency
    if cap is not None and concurrency > cap:
        print(f"Provider is rate-limited: forcing concurrency={cap}")
        concurrency = cap

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
