---
title: Syllabus and coverage
description: The syllabus covers one country at a time.
---

WAEC syllabi are country-partitioned: a topic may be Nigeria-only, Ghana-only, or
shared, so there is no single "WAEC syllabus" — the catalog resolves to the
country you pass in. NECO is Nigeria-only.

## Nigeria (JAMB + NECO)

JAMB and NECO syllabi are not country partitioned at all: every topic is
universal, and the exam is the whole scope. Use:

```text
?exam=JAMB
?exam=NECO
```

## Ghana (WAEC Ghana)

WAEC Ghana is the same `WAEC` exam code as everywhere else; the Ghana slice is
selected with `country=GH`. A topic tagged for Ghana is served when you pass
`country=GH`; no scope rows means universal. Use:

```text
?exam=WAEC&country=GH
```

## Countries that are live but not a page

WAEC's other neighbours — Sierra Leone (`SL`), The Gambia (`GM`), Liberia (`LR`) —
are the same `WAEC` exam with country-scoped topics. They need no new routes:

```text
?exam=WAEC&country=SL
?exam=WAEC&country=GM
?exam=WAEC&country=LR
```

## Coverage gaps

- Not every subject has a syllabus page yet; the catalog lists the slugs above
  and each subject's coverage endpoint returns its topic tree.
- POST-UTME is planned but not in the catalog yet (see [request coverage](catalog/request)).
