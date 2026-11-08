---
title: Quickstart
description: Get your first question from the UTME Lab API in under a minute.
---

## Quickstart

1. Get an API key — email [dev@utmelab.com](mailto:dev@utmelab.com). Self-serve signup isn't open yet.
2. Copy the code below, replace `YOUR_KEY`, and run it:

```bash
curl -s "https://api.utmelab.com/api/v1/questions?exam=JAMB&subject=use-of-english&page=1&per_page=5" \
  -H 'x-api-key: YOUR_KEY'
```

3. Read the `questions` array. Each `id` is your stable reference for that
   row: fetch it later with `/api/v1/questions/{id}`, and flag trouble
   with `POST /api/v1/report`.

## What you just called

Five JAMB Use of English rows. The `exam` filter takes three codes today:

| exam code | coverage |
|---|---|
| `JAMB` | Nigeria. 25/25 subjects served, 2,241 questions (2025 cohort). |
| `WAEC` | Nigeria, Ghana, Sierra Leone, The Gambia, Liberia. 6 subjects catalogued, syllabi split by `country`. Question depth is still growing. |
| `NECO` | Nigeria. 3 subjects catalogued. Question depth is still growing. |

`POST-UTME` is planned and returns `404` for now. Boards and countries
outside the table above aren't new routes — they're new catalog rows. Ask
for them on the [request coverage](/docs/guides/catalog/request/) page.

## Key details that matter

- **Base URL:** `https://api.utmelab.com` (production).
- **Auth header:** every metered call needs `x-api-key: <key>` (raw key, no
  scheme), or a short-lived bearer token as described below.
  Keys are issued by email for now; dashboard issue/rotation comes with accounts.
- **Rate limits:** 60 requests/minute per key. Over that you get `429` with
  a `Retry-After` header. Wait as told, then retry.

## Calling from a browser or app

Keep your key on a server. A key shipped inside a browser bundle, desktop app,
or mobile binary can be extracted, and whoever extracts it shares your quota.
If the client must call the API directly, mint a short-lived token on your
backend and hand the client that instead:

```bash
curl -s -X POST "https://api.utmelab.com/api/v1/tokens" \
  -H 'x-api-key: YOUR_KEY' \
  -H 'content-type: application/json' \
  -d '{"expires_in": 300}'
```

```json
{
  "access_token": "tok_...",
  "token_type": "Bearer",
  "expires_in": 300,
  "scopes": ["read:catalog"]
}
```

The client then sends the token in the standard header:

```bash
curl -s "https://api.utmelab.com/api/v1/questions?exam=JAMB&subject=use-of-english" \
  -H 'authorization: Bearer tok_...'
```

What the token can and cannot do:

- It reads the catalog and nothing else. No reports, no key management, no MCP.
- It lives between 60 and 900 seconds. `expires_in` is a request; the response
  states the lifetime actually granted, capped at 15 minutes.
- Only a secret key can mint one. A token cannot mint another token, so a
  leaked token cannot refresh itself.
- Quota is billed to the key that minted it, so minting more tokens never buys
  a fresh bucket.
- Revoking or narrowing the parent key applies to every token it minted, on the
  next request.
- Send exactly one credential. A request carrying both `x-api-key` and
  `authorization` is refused with `401`.

## Response envelope

A list response looks like this (fields trimmed — the real row for this
query holds 167 records over 34 pages):

```json
{
  "questions": [ { "id": "...", "subject": "use-of-english", "text": { "text": "..." } } ],
  "page": 1,
  "per_page": 5,
  "total_pages": 34,
  "total_records": 167,
  "includes_explanation": false
}
```

- `page` / `per_page`: 1-based page controls (`per_page` caps at 200).
- `total_records` / `total_pages`: honest counts for *your filters*, not the
  whole bank. The server is the source of truth for those totals.
- Add `&include_explanation=true` to include the answer and the working.
  Without it, answers never ride the response.

## Filters you will actually use

```text
?exam=JAMB|WAEC|NECO
?subject=use-of-english            # subject slug within that exam
?country=GH                        # WAEC Ghana filter (country-partitioned syllabi)
?verified=true                     # only human-reviewed questions
?source=past_paper                 # provenance: past_paper | claimed_paper | authored | imported
?year=2025                         # exam cohort the question was prepared for
?q=passage                         # substring of the question text
```

That's the whole first call. The [full route surface](/) is on the landing
page; the raw spec downloads at `/openapi.json` for Postman or Insomnia.
