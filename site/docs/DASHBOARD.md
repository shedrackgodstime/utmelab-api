# Dashboard — scaffolded, not built

**Status:** structure decided and initialised. **No product decisions made.**
Nothing here is implemented; every panel is a placeholder.
**Started:** 2026-10-12.

> This file is the pickup note. Read it, then pick the next item in §5.

---

## 1. What exists

```
src/layouts/Dashboard.astro        shell: drawer sidebar + navbar + main
src/styles/dashboard.css           daisyUI + the brand theme
src/pages/dashboard/index.astro         → /dashboard/            Overview
src/pages/dashboard/api-key/index.astro → /dashboard/api-key/    API key
src/pages/dashboard/billing/index.astro → /dashboard/billing/    Billing & account
```

The three sidebar sections are the only content decision made: **overview, API
key, billing/account**. What each one *shows* is undecided — deliberately. It
waits on `/internal/v1/*`, which does not exist yet.

## 2. The stack, and why

**daisyUI on Tailwind v4.** Design blocks are classes you drop in — `card`,
`stats`, `stat`, `btn`, `table`, `badge`, `alert`, `menu`, `drawer`. You import
what you need; you do not hand-build components, and there is no component
library to fight.

Rejected, for the record:

- **Pico CSS** — the obvious "classless, zero-effort" pick, but it is
  **unmaintained** (final release v2.1.1). Not a dependency worth taking.
- **Bootstrap** — literally built for dashboards, and it looks like 2015.
- **A React/Preact island** — the dashboard needs interactivity eventually, but
  it does not need a virtual DOM yet, and D32 means we would rather not ship one.
- **A community Starlight theme** — the docs question is separate; see §6.

## 3. The one thing that will bite you

`dashboard.css` is imported by `Dashboard.astro` **only**. That is deliberate:

- daisyUI writes its theme onto `:root`, so importing it globally repaints the
  Starlight docs as well
- Tailwind v4's **preflight is deliberately not imported** — it is a global reset
  and would fight Starlight's own cascade layer

Verified: `/dashboard/*` loads only `Dashboard.*.css`; `/docs/*` loads only
Starlight's sheets; `/` loads none. **If you ever import `dashboard.css` from a
shared entrypoint, check that isolation again.**

## 4. Themed, not generic

`dashboard.css` defines two daisyUI themes, `utmelab` and `utmelab-dark`, on the
same teal as the marketing pages (`#0f766e` / `#2dd4bf`). Theme switching is
`data-theme` on `<html>` — the dashboard shell hardcodes `utmelab` today; wiring
Starlight's light/dark/auto picker to it is an open item in §5.

> **Known drift:** the landing page and this dashboard still declare their own
> `--accent`/`--ink`/`--muted`/`--line` inline, while `app.css` uses
> `--utmelab-*` and the docs use `--sl-*`. Three token systems, two duplicated
> blocks. Consolidating them is item 1 of §5 — it is the thing most likely to
> become painful.

## 5. Next, in order

1. **Unify the design tokens.** One `src/styles/tokens.css` feeding the landing
   page, the dashboard and the docs, mapped into `--sl-*`. Highest value, no
   product decisions needed.
2. **Wire `data-theme` to a real light/dark switch**, and pick the font (still
   `system-ui` everywhere — the single biggest "generic" tell).
3. **Decide what `/internal/v1/*` serves first.** `GET /internal/v1/me` is the
   obvious first endpoint: the shell needs a signed-in identity before anything
   else can render. Session cookie, never API key; never in the public spec (D33).
4. **Then** replace the placeholders with real data. One panel at a time —
   Overview first, since it is what a returning customer wants.
5. **Then** the product decisions: plan tiers, what usage is metered on,
   whether invoices exist before billing is switched on. All currently parked.

## 6. Open, from the docs thread

The docs still read generic. Diagnosis is that font, logo and the gray scale are
untouched — Starlight's defaults otherwise look fine. Options researched:
official `customCss` design tokens (with their built-in theme designer), or a
community theme from the official gallery (Lucode is the product-docs-flavoured
one). **Not decided — see §5.2.**

## 7. Do not

- **Do not add a UI framework** on top of daisyUI. One styling system.
- **Do not import Tailwind preflight** or `dashboard.css` globally.
- **Do not design the product here.** This scaffold exists so that the next
  session starts from a decided structure rather than an empty directory.