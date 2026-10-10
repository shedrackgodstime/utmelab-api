---
title: Errors
description: Every failure is an RFC 9457 problem document.
---

## One shape, every time

Errors use [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem documents, served as
`application/problem+json`:

```json
{
  "type": "https://docs.utmelab.com/errors/subject_not_found",
  "title": "Not found",
  "status": 404,
  "detail": "No subject with slug 'mathetics' for exam 'JAMB'.",
  "code": "subject_not_found"
}
```

`status` and the HTTP status always agree. `code` is stable and machine-readable — branch on
that, not on `detail`, which is written for humans and may be reworded.

## Codes

| `code` | Status | Means |
|---|---|---|
| `unauthorized` | 401 | Missing, unknown or revoked key |
| `rate_limited` | 429 | Over this key's per-minute limit |
| `subject_not_found` | 404 | No such subject **in that exam** |
| `exam_not_found` | 404 | No such exam |
| `route_not_found` | 404 | No such endpoint |
| `filter_required` | 404 | No usable filter on `/questions` |

## Two things that will surprise you

**A missing key and a wrong key are the same 401.** We do not tell you which, and we do
not tell you whether a key id exists. You cannot enumerate valid keys through error
responses.

**A subject not found means "not in *that exam*."** `Use of English` is a JAMB subject;
WAEC calls the same subject `English Language`. Asking for the wrong pairing is a 404,
because the exam is genuinely part of the subject's identity.

## No internal detail is ever returned

Configuration failures, database errors and internal messages are logged server-side and
replaced with a generic detail in the response. A stack trace or a query string in an
error body is a leak.
