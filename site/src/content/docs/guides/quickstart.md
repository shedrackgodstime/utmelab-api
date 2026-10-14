---
title: Quickstart
description: Get your first question from the UTME Lab API in under a minute.
---

## Quickstart

1. [Sign in to the dashboard](/dashboard/signin/) and create an API key.
2. Copy the code below, replace `YOUR_KEY`, and run it:

```bash
curl -s https://api.utmelab.com/api/v1/questions?exam=JAMB&subject=use-of-english&page=1&per_page=5 \
  -H 'Authorization: Bearer YOUR_KEY'
```

3. Read the first `question` in `data`. The `id` it returns is your stable
   reference for every later call (fetch it with
   `/api/v1/questions/{id}`, paginate with the `page`/`per_page` params below,
   and report trouble with the `report` route).

## What you just called

The example lists five of the questions in the catalog. It uses two of the three
exam codes the API accepts:

| exam code | countries | flavour |
|---|---|---|
| `JAMB` | Nigeria | The unified tertiary entrance exam (UTME). 25 subjects served. |
| `NECO` | Nigeria | National Examinations Council SSCE. 3 subjects served. |
| `WAEC` | Nigeria, Ghana, Sierra Leone, The Gambia, Liberia | 8 subjects, country-partitioned syllabi. Pass `country=` to filter (see below). |

POST-UTME is [planned](catalog) and is **not** accepted as an exam code yet
(valid requests for it return `404` until it lands).

## Key details that matter

- **Base URL:** `https://api.utmelab.com` (production). See [environments](authentication#environments) for staging.
- **Auth header:** every metered call needs `Authorization: Bearer <key>`. Keys are issued and rotated in the dashboard (see [authentication](authentication)).
- **Rate limits:** metered per key. See [limits](rate-limits).

## Response envelope

A list response looks like this (fields trimmed):

```json
{
  "questions": [ { "id": "...", "subject": "use-of-english", "text": "..." } ],
  "page": 1,
  "per_page": 5,
  "total_pages": 449,
  "total_records": 2244,
  "includes_explanation": false
}
```

- `page` / `per_page`: 1-based page controls.
- `total_records` / `total_pages`: honest counts. `total_records` is the
  number of questions that match your filters, not the whole bank. The
  server is the source of truth for those totals.
- Add `&include_explanation=true` to include the answer and the working.

## Filters you will actually use

```text
?exam=JAMB|WAEC|NECO
?subject=use-of-english            # subject slug within that exam
?country=GH                        # WAEC Ghana filter (country-partitioned syllabi)
?verified=true                     # only reviewed questions
?source=past_paper                 # provenance: past_paper | claimed_paper | authored | imported
?year=2025                         # exam cohort the question was prepared for
?q=passage                         # substring of the question text
```

See [browsing the catalog](catalog) for the full filter reference and the
subject/slug table.
