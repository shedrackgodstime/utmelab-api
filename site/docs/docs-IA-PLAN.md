# Docs IA Plan (pinned — do not drift)

Decision: exam bodies are DATA, not sidebar sections. One stable endpoint
surface (`/api/v1/*`); bodies + countries are enum filters. Growth = new
catalog rows, never redesign.

## The tree as shipped (v0.1.0)

Starlight, hand-listed top level only. Autogenerate is used for the Guides
group alone — never for the whole tree, so top-level order stays deliberate:

```
Introduction   link /  (Starlight prepends the base; never write /docs/ here)
Quickstart     slug guides/quickstart  (first call in ~2 min, JAMB-first)
Guides         collapsed, autogenerate guides/catalog/
  └── Request coverage                (boards/countries not yet served)
```

Growth rule: new guides go under `guides/` and get a hand-listed top-level
or Guides-group entry at write time — a slug in the config must be a file
on disk. No phantom entries, ever.

## API Reference (generated, not written)

`API Reference` in the sidebar is built at docs-build time by
`starlight-openapi` from `site/openapi.json`. That file is emitted by
`cargo run -- openapi --out site/openapi.json` and committed — the docs
never hand-describe an endpoint. After any route/shape change:

1. Re-emit the spec, commit it.
2. Every op needs `operation_id` + one-line `summary` (sidebar labels render
   the summary; no summary looks dumped). Tags must exist in the `tags`
   list in `src/api/openapi.rs`.
3. `site` build regenerates the 20+ reference pages; `merge.mjs` also copies
   the spec to `dist/openapi.json` for the download links.

## Why this shape (evidence)

- Bodies-as-filters matches the wire: `?exam=JAMB|WAEC|NECO`,
  `?country=GH`, subject slugs per exam. A Ghana page would duplicate every
  endpoint page with one filter changed — so coverage lives in rows + one
  request page, never in sections.
- Curated reference over spec dumps: the spec (`GET /openapi.json`) stays
  downloadable for Postman/Insomnia; the docs explain, the spec declares.
- Diátaxis in one axis: guides are task-based (`quickstart`, `request`);
  the catalog request page is the single doorway for "is X covered?".

## Identifiers (exactly as on the wire — never prettified)

- Exam codes: `JAMB`, `WAEC`, `NECO` (uppercase). `POST-UTME` is planned and
  returns `404` until it lands — documented as planned, never as served.
- Country codes: `NG`, `GH`, `SL`, `GM`, `LR` (WAEC partition filter).
- Subject slugs are per-exam (`use-of-english` for JAMB vs
  `english-language` for WAEC). The catalog owns the table; guides link it.
- Routes keep the `/api/v1` prefix in every example. Answers ride only
  `?include_explanation=true`; there is no `/explanations/{id}` and no
  `/search` (substring lives in `?q=`).

## Rules for every docs edit

1. No link to a page that doesn't exist. Relative links only to shipped
   pages; everything else is plain text until the page lands.
2. No exam-first examples outside JAMB: the bank is 2,241/2,243 JAMB.
   WAEC/NECO examples wait for real depth.
3. Numbers come from `data/` at write time (counts, pages, cohorts) and the
   source is named. Never round a count into a claim.
4. Auth copy matches reality: keys are issued manually today
   (`dev@utmelab.com`); self-serve signup/rotation are coming soon and are
   labeled so wherever mentioned.
5. Future countries are requests, not roadmap: the request page takes them;
   no page promises a board by name or date.

## Deferred (no page until the thing exists)

- Pricing/limits copy, authentication rotation guide, pagination/caching
  cookbooks, Scalar playground, per-group reference pages, changelogs.
