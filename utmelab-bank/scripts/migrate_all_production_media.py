"""Move every production source image to the content-addressed media store.

The default is a read-only dry run. ``--apply`` is required to upload files
and update production rows. The script keeps every image position unchanged,
recomputes the production content hash, and updates matching verification
hashes in the same database transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace as N
from typing import Any
from urllib.parse import quote

import httpx
import turso_serverless

from utmelab_bank.domain.hashing import content_fingerprint

PAGE_SIZE = 100


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


def _value(values: dict[str, str], *names: str) -> str:
    for name in names:
        if values.get(name):
            return values[name]
    return ""


def _db(values: dict[str, str], *, apply: bool) -> Any:
    url = _value(values, "TURSO_DB_URL", "TURSO_PROD_DATABASE_URL")
    token_names = ("TURSO_DB_TOKEN", "TURSO_PROD_AUTH_TOKEN") if apply else (
        "TURSO_PROD_AUTH_TOKEN_READONLY",
        "TURSO_DB_TOKEN_READONLY",
        "TURSO_DB_TOKEN",
        "TURSO_PROD_AUTH_TOKEN",
    )
    token = _value(values, *token_names)
    if not url or not token:
        raise RuntimeError("production database URL and token are required")
    return turso_serverless.connect(url, auth_token=token)


def _rich(text: str, inline: list[dict[str, Any]]) -> Any:
    marks = []
    for mark in inline:
        data = dict(mark)
        data.setdefault("alt", None)
        marks.append(N(**data))
    return N(text=text, inline=marks)


def _replace_images(value: Any, replacements: dict[str, str], found: list[tuple[str, str]]) -> Any:
    if isinstance(value, list):
        return [_replace_images(item, replacements, found) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _replace_images(item, replacements, found) for key, item in value.items()}
    if result.get("kind") == "image":
        url = result.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            filename = replacements[url]
            result["url"] = filename
            found.append((url, filename))
    return result


def _source_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, list):
        for item in value:
            urls.extend(_source_urls(item))
    elif isinstance(value, dict):
        if value.get("kind") == "image" and isinstance(value.get("url"), str):
            url = value["url"]
            if url.startswith(("http://", "https://")):
                urls.append(url)
        for item in value.values():
            urls.extend(_source_urls(item))
    return urls


def _fingerprint(row: tuple[Any, ...], updated: dict[str, Any]) -> str:
    _id, text, _inline, _options_raw, answer, _explanation_raw, _old_hash = row
    options = updated["options"]
    explanation = updated["explanation"]
    choices = [
        N(id=option["id"], text=_rich(option["text"]["text"], option["text"].get("inline", [])))
        for option in options
    ]
    exp = None
    if explanation is not None:
        exp = N(
            key_point=_rich(explanation["key_point"]["text"], explanation["key_point"].get("inline", [])),
            body=_rich(explanation["body"]["text"], explanation["body"].get("inline", [])),
            trap=(
                _rich(explanation["trap"]["text"], explanation["trap"].get("inline", []))
                if explanation.get("trap")
                else None
            ),
        )
    return content_fingerprint(
        stem=_rich(text, updated["inline"]),
        options=choices,
        answer=answer,
        explanation=exp,
    )


async def _download(client: httpx.AsyncClient, url: str) -> tuple[bytes, str]:
    response = await client.get(url)
    response.raise_for_status()
    mime = response.headers.get("content-type", "image/png").split(";", 1)[0]
    return response.content, mime


async def _upload(
    client: httpx.AsyncClient,
    *,
    host: str,
    project: str,
    token: str,
    branch: str,
    filename: str,
    data: bytes,
) -> None:
    api = f"https://{host}/api/v4/projects/{quote(project, safe='')}"
    path = quote(f"images/{filename}", safe="")
    headers = {"PRIVATE-TOKEN": token}
    check = await _gitlab_request(
        client,
        "GET",
        f"{api}/repository/files/{path}?ref={quote(branch, safe='')}",
        headers=headers,
    )
    if check.status_code == 200:
        return
    if check.status_code != 404:
        check.raise_for_status()
    body = {
        "branch": branch,
        "content": base64.b64encode(data).decode("ascii"),
        "encoding": "base64",
        "commit_message": f"add figure {filename}",
    }
    created = await _gitlab_request(
        client,
        "POST",
        f"{api}/repository/files/{path}",
        headers=headers,
        json=body,
    )
    if created.status_code not in (201, 400):
        created.raise_for_status()
    raw = await _gitlab_request(
        client,
        "GET",
        f"{api}/repository/files/{path}/raw?ref={quote(branch, safe='')}", headers=headers
    )
    raw.raise_for_status()
    if hashlib.sha256(raw.content).digest() != hashlib.sha256(data).digest():
        raise RuntimeError(f"GitLab returned different bytes for {filename}")


async def _gitlab_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Retry transient GitLab throttling and server failures."""
    for attempt in range(6):
        response = await client.request(method, url, **kwargs)
        if response.status_code not in (429, 500, 502, 503, 504):
            return response
        retry_after = response.headers.get("retry-after")
        try:
            delay = float(retry_after) if retry_after else min(2**attempt, 30)
        except ValueError:
            delay = min(2**attempt, 30)
        await asyncio.sleep(max(1.0, min(delay, 60.0)))
    return response


async def migrate(args: argparse.Namespace) -> None:
    values = _env_file()
    connection = _db(values, apply=args.apply)
    gitlab_token = _value(values, "GITLAB_TOKEN")
    project = _value(values, "GITLAB_MEDIA_REPO")
    branch = _value(values, "UTMELAB_BANK_MEDIA_BRANCH") or "main"
    rows: list[tuple[Any, ...]] = []
    cursor = ""
    while True:
        page_args = [cursor]
        page_conditions = ["id > ?"]
        if args.exam:
            page_conditions.append("exam = ?")
            page_args.append(args.exam)
        if args.subject:
            page_conditions.append("subject = ?")
            page_args.append(args.subject)
        if args.year:
            page_conditions.append("year = ?")
            page_args.append(args.year)
        page = connection.execute(
            "SELECT id,text,inline,options,answer,explanation,content_hash "
            "FROM questions WHERE " + " AND ".join(page_conditions) + " ORDER BY id LIMIT ?",
            [*page_args, PAGE_SIZE],
        ).fetchall()
        if not page:
            break
        rows.extend(page)
        cursor = str(page[-1][0])
        if args.limit and len(rows) >= args.limit:
            rows = rows[: args.limit]
            break
        if len(page) < PAGE_SIZE:
            break

    plans: list[tuple[str, str, str, str, str, str | None, dict[str, bytes]]] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for row in rows:
            inline = json.loads(row[2])
            options = json.loads(row[3])
            explanation = json.loads(row[5]) if row[5] else None
            source_values = [inline, options, explanation]
            urls = sorted(set(url for value in source_values for url in _source_urls(value)))
            if not urls:
                continue
            replacements: dict[str, str] = {}
            files: dict[str, bytes] = {}
            for url in urls:
                data, mime = await _download(client, url)
                digest = hashlib.sha256(data).hexdigest()
                suffix = Path(url.split("?", 1)[0]).suffix.lower() or ".png"
                filename = f"{digest}{suffix}"
                replacements[url] = filename
                files[filename] = data
                print(f"{row[0]}: {url} -> {filename} ({mime}, {len(data)} bytes)")
            updated = {
                "inline": _replace_images(inline, replacements, []),
                "options": _replace_images(options, replacements, []),
                "explanation": _replace_images(explanation, replacements, [])
                if explanation is not None
                else None,
            }
            new_hash = _fingerprint(row, updated)
            plans.append(
                (
                    row[0],
                    row[6],
                    new_hash,
                    json.dumps(updated["inline"], ensure_ascii=False),
                    json.dumps(updated["options"], ensure_ascii=False),
                    json.dumps(updated["explanation"], ensure_ascii=False)
                    if updated["explanation"] is not None
                    else None,
                    files,
                )
            )
            if args.apply:
                if not gitlab_token or not project:
                    raise RuntimeError("GITLAB_TOKEN and GITLAB_MEDIA_REPO are required with --apply")
                for filename, data in files.items():
                    await _upload(
                        client,
                        host=_value(values, "GITLAB_HOST") or "gitlab.com",
                        project=project,
                        token=gitlab_token,
                        branch=branch,
                        filename=filename,
                        data=data,
                    )

    if not args.apply:
        print(f"dry run only; {len(plans)} question(s) would change")
        connection.close()
        return

    try:
        connection.execute("BEGIN")
        for question_id, old_hash, new_hash, inline, options, explanation, _files in plans:
            connection.execute(
                "UPDATE questions SET inline = ?, options = ?, explanation = ?, content_hash = ? "
                "WHERE id = ? AND content_hash = ?",
                [inline, options, explanation, new_hash, question_id, old_hash],
            )
            changed = connection.execute("SELECT changes() as changed").fetchone()[0]
            if changed != 1:
                raise RuntimeError(f"production row changed before migration: {question_id}")
            connection.execute(
                "UPDATE verifications SET content_hash = ? WHERE question_id = ? AND content_hash = ?",
                [new_hash, question_id, old_hash],
            )
        connection.commit()
        print(f"applied {len(plans)} question migration(s)")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="upload files and update production")
    parser.add_argument("--limit", type=int, default=None, help="limit questions scanned")
    parser.add_argument("--exam", default=None)
    parser.add_argument("--subject", default=None)
    parser.add_argument("--year", type=int, default=None)
    asyncio.run(migrate(parser.parse_args()))


if __name__ == "__main__":
    main()
