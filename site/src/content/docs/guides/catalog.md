---
title: Browsing the catalog
description: How coverage works — exam bodies are filters, not routes.
---

The catalog is a flat endpoint surface with **three exam codes** and a **`country`
filter**. There are no exam-body routes: the same `/questions`, `/subjects`,
`/papers` and `/topics` endpoints serve JAMB, NECO and WAEC, and a country is a
query filter, not a section of the API.

## Exam codes reference

| code | exam | countries | subjects | status |
|---|---|---|---|---|
| `JAMB` | Joint Admissions and Matriculation Board — UTME | Nigeria (`NG`) | 25 | live |
| `NECO` | National Examinations Council — SSCE | Nigeria (`NG`) | 3 | live |
| `WAEC` | West African Examinations Council — WASSCE | Nigeria, Ghana, Sierra Leone, The Gambia, Liberia (`NG`, `GH`, `SL`, `GM`, `LR`) | 8 | live |

The accepted exam codes are the subject rows in `subjects.json`: **JAMB, NECO,
WAEC**. POST-UTME is [planned](catalog/request) and is intentionally not yet in
the catalog; it will enter as one more row (code, country set, subjects), never as
a new route.

## Filter reference

Every list endpoint accepts:

| param | values | meaning |
|---|---|---|
| `exam` | `JAMB` \| `NECO` \| `WAEC` | scope to an exam |
| `subject` | subject slug | scope to one subject |
| `year` | e.g. `2025` | exam cohort the question was prepared for |
| `q` | substring | question text, case-insensitive |
| `verified` | `true` \| `false` | reviewed vs un-reviewed |
| `source` | `past_paper` \| `claimed_paper` \| `authored` \| `imported` | provenance |
| `country` | `NG` \| `GH` \| `SL` \| `GM` \| `LR` | country-scoped filter (WAEC syllabi are country-partitioned) |

Country filter semantics: a topic is in scope for a country when it carries no
scope rows (universal) or when one of its scope rows names the country. A topic
with several countries covers all of them. Filter absent → the full catalog.

## Subject slugs (stable identifiers)

Each subject is keyed by `(exam, slug)`. The slugs below are the ones to pass as
the `subject` param:

| exam | slugs (subject → exam) |
|---|---|
| `JAMB` (25) | `agricultural-science`, `arabic`, `art`, `biology`, `chemistry`, `christian-religious-studies`, `commerce`, `computer-studies`, `economics`, `french`, `geography`, `government`, `hausa`, `history`, `home-economics`, `igbo`, `islamic-religious-studies`, `literature-in-english`, `mathematics`, `music`, `physical-education`, `physics`, `principles-of-accounts`, `use-of-english`, `yoruba` |
| `NECO` (3) | `animal-husbandry`, `civic-education`, `english-language` |
| `WAEC` (8) | `agricultural-science`, `civic-education`, `commerce`, `computer-studies`, `data-processing`, `economics`, `financial-accounting`, `physics` |

Subjects, years and coverage counts change with the catalog, but the endpoints,
the query enums and the slug vocabulary stay the same: new coverage lands as new
catalog rows, never as new routes.

## Request coverage for unlisted boards

Not every board is in the catalog yet. Boards outside the live set (e.g. KCSE,
UNEB, NSC) are served through [request coverage](catalog/request) — content work,
never engineering work.
