---
title: Pagination
description: page, per_page, and totals that do not lie.
---

## Simple paging, deliberately

```
page          1-based. Default 1.
per_page      Default 50. Capped at 200.
```

```bash
curl "https://api.utmelab.com/api/v1/questions?subtopic=change-of-bases&page=2&per_page=25" \
  -H "X-API-Key: $UTMELAB_API_KEY"
```

```json
{
  "questions": [ /* … */ ],
  "page": 2,
  "per_page": 25,
  "total_pages": 3,
  "total_records": 68
}
```

No cursors, no opaque tokens, no surprises. `page` and `per_page` mean what they say.

## The cap is the point

`per_page` is capped at **200**. That is deliberate: it is not possible to ask for the
whole bank in one request, so no single call can be used to melt the service.

## Totals stay true

`total_records` counts **everything matching the filter**, not the current page — so a
progress bar built from it is honest.

Asking for a page past the end returns an empty `questions` array and **still reports the
real totals**. That is deliberate: an empty page is an answer, not an error.

```
?page=99  →  { "questions": [], "page": 99, "total_pages": 3, "total_records": 68 }
```

Filters are applied **before** paging, so `total_records` reflects them.

## Order is stable

Results are ordered by question id, so a page boundary means the same thing on every
request. Your integration does not silently shift under you.
