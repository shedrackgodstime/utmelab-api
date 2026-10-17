# Notes from the Jamb-Lab consumer (contributor)

> Filed 2026-10-11 while wiring Jamb-Lab (Vite client) to this API.
> Nothing here changes behavior — open items for the API owner, plus
> context the client already handles. §1 resolved (see below); §§2–3 stay
> open client context — do not delete this file while they do.

## 1. Broken image on a verified row (resolved 2026-10-11, D55)

- Row: `q_authored_physics_shm_002` (physics, JAMB 2025, authored)
- It asks about a displacement-time graph but points at the relative path
  `diagrams/shm_displacement_time.svg`, which is served by nothing —
  this API serves JSON only, and no static host carries that path.
- The other 71 image rows use absolute CDN URLs and work fine; this is
  the single outlier (`non-absolute: 1` across the whole bank).
- Without the graph the question is unanswerable, same class as the
  78 underline questions already tracked in `TODO.md`.
- Resolved as: dead path stripped, image gone, `verified:false` (D55) — the
  mirror job restores both when the asset repo exists. Client note stands:
  Jamb-Lab drops dead `<img>` via its error handler and renders text-only.

## 2. Client context (for orientation, not action)

- Jamb-Lab reads the catalog (`GET /api/v1/exams/JAMB/subjects`, keyless)
  as the subject source of truth and pages `/questions` with
  `include_explanation=true` (answer id → option index locally).
- One deployment key (`jamb-lab-turso`, Turso backend, 60 req/min).
  Turso is the only key store; `var/` file backend is retired locally.
- CORS `*` + `x-api-key` allowed is what makes the browser client work.
- Repeat visits are served from a version-gated `localStorage` cache:
  one keyless `GET /health` proves `bank_version` current (zero question
  requests), any content fix refetches on the next boot. No TTL anywhere.

## 3. Caching suggestions for the owner (review, not demands)

Checked against `src/api/middleware.rs` — ETag/304, `Cache-Control`
(questions 60s, catalog 1h) and token-free 304s already exist, so the
cheap wins are taken. Remaining thoughts:

- `Cache-Control: public` on the metered `/questions` responses deserves
  a second look: a shared cache honoring it could serve paid-tier rows to
  URL-holders with no key. `private` (or keyed-by-URL verification) may
  match the D27 metering intent better. Flagging, not asserting — depends
  on what actually sits in front of the binary.
- If a bulk/sync shape ever lands (version + per-subject counts in one
  call), keyless clients like this one could diff in 1 request instead of
  N. Not needed today: `bank_version` from `/health` already covers the
  invalidation half, which is all the client cache relies on.
