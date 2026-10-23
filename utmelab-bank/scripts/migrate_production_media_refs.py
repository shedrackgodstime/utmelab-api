"""Replace verified source image URLs with canonical asset filenames.

This is a one-time content migration. It is intentionally not part of the
normal bank workflow. Run it once in dry-run mode, inspect the plan, then run
it with ``--apply`` against the production database.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace as N
from typing import Any

import turso_serverless

from utmelab_bank.domain.hashing import content_fingerprint

ASSETS: dict[str, str] = {
    "q_claim_2025_biology_74398": "8d709ebf73ddef75db2dc8843950f29c792e05fb741063261e4073ca06fa7147.png",
    "q_claim_2025_biology_74403": "f3bbd237b969d016a23bf17d1cb7ec8ff099a24284c93ec582a8cd1029d51dc2.png",
    "q_claim_2025_biology_74406": "97c68f56046c2cc96508e96f6c37c4b0934ce495db466c506b8b0502e8b9a216.png",
    "q_claim_2025_biology_74441": "c67490cef0263b04b58968876770e57b6be5c9be224fe2acdaf8bc428e55d373.png",
    "q_claim_2025_biology_74473": "783ed4a3f396f8eb3f2a627635f1308277a4f1639af476dd03f692ecd0d4309d.png",
    "q_claim_2025_biology_74496": "3ee8e811c3c61e399f2ac333a41ee76f46bb6179038b9ae8ead302e49ea6ef7b.png",
    "q_claim_2025_biology_74497": "94ba097bf835fb9c7ad7d718addb6bed262a34a15c22532222c8415c8b3f57ac.png",
    "q_claim_2025_biology_74505": "561f5f6126494808afc0e6a1d7e1e043e28df6d209c2890c9308858aa47b59f3.png",
    "q_claim_2025_biology_74519": "b80941357c6fe4f8294f6dc4a3269a59b23d81a4890e4cd43c628f35ca2744f5.png",
}


def _env_file() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / ".env"
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip().strip('"').strip("'")
    values.update({key: value for key, value in os.environ.items() if value})
    return values


def _connection() -> Any:
    values = _env_file()
    url = values.get("TURSO_DB_URL") or values.get("TURSO_PROD_DATABASE_URL")
    token = values.get("TURSO_DB_TOKEN") or values.get("TURSO_PROD_AUTH_TOKEN")
    if not url or not token:
        raise RuntimeError("set TURSO_DB_URL and TURSO_DB_TOKEN for this migration")
    return turso_serverless.connect(url, auth_token=token)


def _rich(text: str, inline: list[dict[str, Any]], *, replacement: str | None = None) -> Any:
    marks: list[Any] = []
    for mark in inline:
        data = dict(mark)
        data.setdefault("alt", None)
        if replacement is not None and data.get("kind") == "image":
            data["url"] = replacement
        marks.append(N(**data))
    return N(text=text, inline=marks)


def _fingerprint(
    *,
    text: str,
    inline: list[dict[str, Any]],
    options: list[dict[str, Any]],
    answer: str,
    explanation: dict[str, Any] | None,
    replacement: str,
) -> tuple[str, list[dict[str, Any]]]:
    updated_inline = [dict(mark) for mark in inline]
    images = [mark for mark in updated_inline if mark.get("kind") == "image"]
    if len(images) != 1 or images[0].get("position") != "above":
        raise RuntimeError("expected exactly one stem image positioned above")
    images[0]["url"] = replacement

    choices = [
        N(
            id=option["id"],
            text=_rich(option["text"]["text"], option["text"].get("inline", [])),
        )
        for option in options
    ]
    exp = None
    if explanation is not None:
        exp = N(
            key_point=_rich(
                explanation["key_point"]["text"], explanation["key_point"].get("inline", [])
            ),
            body=_rich(explanation["body"]["text"], explanation["body"].get("inline", [])),
            trap=(
                _rich(explanation["trap"]["text"], explanation["trap"].get("inline", []))
                if explanation.get("trap")
                else None
            ),
        )
    return (
        content_fingerprint(
            stem=_rich(text, updated_inline),
            options=choices,
            answer=answer,
            explanation=exp,
        ),
        updated_inline,
    )


def migrate(*, apply: bool) -> None:
    connection = _connection()
    plans: list[tuple[str, str, str, str, str]] = []
    try:
        for question_id, filename in ASSETS.items():
            rows = connection.execute(
                "SELECT text, inline, options, answer, explanation, content_hash "
                "FROM questions WHERE id = ?",
                [question_id],
            ).fetchall()
            if len(rows) != 1:
                raise RuntimeError(f"expected one production row for {question_id}")
            text, inline_raw, options_raw, answer, explanation_raw, old_hash = rows[0]
            inline = json.loads(inline_raw)
            options = json.loads(options_raw)
            explanation = json.loads(explanation_raw) if explanation_raw else None
            new_hash, updated_inline = _fingerprint(
                text=text,
                inline=inline,
                options=options,
                answer=answer,
                explanation=explanation,
                replacement=filename,
            )
            plans.append(
                (question_id, old_hash, new_hash, json.dumps(updated_inline, ensure_ascii=False), filename)
            )
            print(f"{question_id}: {old_hash} -> {new_hash} ({filename})")

        if not apply:
            print("dry run only; no production rows changed")
            return

        connection.execute("BEGIN")
        for question_id, old_hash, new_hash, inline, _ in plans:
            connection.execute(
                "UPDATE questions SET inline = ?, content_hash = ? WHERE id = ? AND content_hash = ?",
                [inline, new_hash, question_id, old_hash],
            )
            connection.execute(
                "UPDATE verifications SET content_hash = ? "
                "WHERE question_id = ? AND content_hash = ?",
                [new_hash, question_id, old_hash],
            )
        connection.commit()
        print(f"applied {len(plans)} production media migrations")
    except Exception:
        try:
            connection.rollback()
        finally:
            connection.close()
        raise
    connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the migration")
    args = parser.parse_args()
    migrate(apply=args.apply)


if __name__ == "__main__":
    main()
