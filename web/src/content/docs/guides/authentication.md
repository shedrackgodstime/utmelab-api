---
title: Authentication
description: One API key, sent in the X-API-Key header.
---

## The catalog needs no key

Listing exams, subjects and syllabi is **free and unauthenticated**. You can render a
whole subject picker before you sign up for anything:

```bash
curl https://api.utmelab.com/api/v1/exams
curl https://api.utmelab.com/api/v1/exams/JAMB/subjects
curl https://api.utmelab.com/api/v1/subjects/JAMB/use-of-english/syllabus
```

Only `/api/v1/questions` and `/api/v1/keys/me` require a key.

## The key

Send it in the `X-API-Key` header:

```bash
curl https://api.utmelab.com/api/v1/keys/me \
  -H "X-API-Key: $UTMELAB_API_KEY"
```

```json
{
  "id": "key_afefd08ac0efd08ac0efd08ac0efd08ac",
  "label": "acme-backend",
  "rate_limit": 600,
  "created_at": "1791643624"
}
```

Check yours with `GET /api/v1/keys/me`. If it answers, the key works.

## One key type — use it from anywhere

There is no "server key" and no "browser key". The same key works from your backend, from
a mobile app, or from `curl`.

**If you embed it in a client app it can be extracted, and whoever extracts it shares
your quota.** That is the trade, and it is deliberate: most integrators here are small
teams building a study app, and forcing every one of them to stand up a backend before
they can show one question would cost more integrators than it protects.

If you need to meter your own users, put a server in front and call the API from there.
Ask for a higher rate limit and we will set it on your key.

## Rate limits

Every key has its own requests-per-minute allowance — a **per-key column**, not a key
type. Exceeding it returns `429` with a problem document; the budget refills continuously
and never exceeds the cap.

Limits are per key, so one busy integrator cannot exhaust another's.

## Revoking

Revocation is immediate and total. An unknown key and a revoked key return **byte-for-byte
the same `401`**, so nobody can enumerate your key ids by watching error responses.
