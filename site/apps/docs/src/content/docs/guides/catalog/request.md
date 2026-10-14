---
title: Request coverage
description: Ask for a board or country that is not in the catalog yet.
---

Only boards with live syllabus coverage are served through the normal catalog
(`JAMB`, `NECO`, `WAEC`). Boards and countries outside that set are not in the
API surface — they are not new routes, they are new catalog rows.

## How to request

1. Tell us the board and the country scope you need (e.g. "Kenya — KCSE", or
   "Sierra Leone — WAEC").
2. We add the coverage as catalog rows: subjects, topics, and year ranges for that
   country/board. The `exam` and `country` query enums grow, and the catalog
   pages update. No migration, no redesign.

## Already covered

- Nigeria — JAMB, NECO, WAEC (`NG`)
- Ghana — WAEC (`GH`)
- Sierra Leone, The Gambia, Liberia — WAEC (`SL`, `GM`, `LR`)

## Coming soon

- NECO exact subject list and compulsory papers (see the research log).
- Non-WAEC boards (KCSE, UNEB, NSC, …).
