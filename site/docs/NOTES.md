# UTME Lab — Site Architecture Notes

> Living planning doc. Anchored at the build root so we don't drift.
> Build root: `utmelab-api/site/ref/site/`  (the OLD `utmelab-api/site/` is abandoned).
> Last updated: planning phase (no code written yet).

---

## 0. North Star

One **domain**, three **surfaces**, one **brand**, one **static build**, detachable later.

- `/`            → marketing / landing  (own shell)
- `/docs/*`      → documentation         (own shell, Starlight)
- `/dashboard/*` → real dashboard        (own shell, NOT derived from Starlight)
- `/signin`, `/signup`, `/terms`, `/pricing` → supporting pages

Each surface has its **own identity (shell)** but shares **one brand** (colors, fonts,
radius, cards, buttons). Built as static HTML, served by Caddy, splittable to
`utmelab.com` / `docs.utmelab.com` / `app.utmelab.com` with **zero rewrite** later.

---

## 1. Why NOT copy Infisical (and what we borrow)

Infisical *fakes* one brand from 3 codebases:

- `infisical.com/`        → marketing. **Private repo**, Next.js on Vercel.
- `infisical.com/docs`    → docs. Public but only inside the monorepo (`/docs` folder),
                            rendered by **Mintlify** (hosted docs-as-a-service).
- `app.infisical.com`     → dashboard. React SPA in the monorepo `frontend/`.

**Red flags we reject:**
- Mintlify = SaaS lock-in: per-seat pricing, pageview limits, theming capped to their
  variables, can't host a real `/dashboard` inside it.
- Dashboard as a React SPA means its own build, its own deploy cadence.
- Landing/dashboard MUST look different from docs (reading vs doing vs selling) —
  different chrome, SEO, cookie isolation, deploy frequency.

**What we borrow:** the *effect* — same brand voice across three shells. But we achieve it
with **one shared brand kit + shared code**, not 3 repos + a vendor.

---

## 2. The Core Rule

> **Share the small stuff, never the shell.**

- SHARE: `tokens.css` (colors/fonts/radius/spacing) + primitives (Button, Card, Input,
  Field, Badge, Note, Table, EmptyState, Logo, ApiKeyField). Dumb, zero layout opinion.
- NEVER SHARE: the shells. `MarketingLayout` lives in `web`, docs layout is Starlight's,
  `AppShell` lives in `app`. If a layout is shared we re-create the Starlight-hack we killed.

```
site/ref/site/
  package.json              # npm workspaces
  packages/ui/              # SHARED brand kit — the ONLY cross-app import
    tokens.css              # the brand contract
    Button.astro Card.astro Input.astro Field.astro
    Badge.astro Note.astro Table.astro EmptyState.astro
    Logo.astro ApiKeyField.astro
  apps/web/                 # LANDING   — pure Astro, no Starlight
    astro.config.mjs        # base: '/',        output: 'static'
    src/layouts/MarketingLayout.astro
    src/pages/index.astro, pricing.astro, terms.astro
  apps/docs/                # DOCS      — Astro + Starlight ONLY here
    astro.config.mjs        # base: '/docs',    output: 'static'
    src/content/docs/*.md
    src/assets/openapi.json # generated from Rust (utoipa), never hand-edited
  apps/app/                 # DASHBOARD — pure Astro, no Starlight import anywhere
    astro.config.mjs        # base: '/dashboard', output: 'static'
    src/layouts/AppShell.astro  # app sidebar + topbar + user menu + full-height
    src/pages/index.astro, api-key.astro, billing.astro, signin.astro
  dist/                     # merged for Caddy now, split later
```

---

## 3. UI Framework Decision — Tailwind v4 everywhere + React/shadcn on the dashboard

**LOCKED (2026-10-14): One styling tool — Tailwind CSS v4 — across ALL surfaces.**
Real shadcn/ui on the dashboard. React stays scoped to the dashboard only.

**The one brand lever = `packages/ui/src/theme.css`** (Tailwind `@theme`, CSS-first).
Every surface imports it after its Tailwind base:
- `apps/web`   → `@import "tailwindcss"` + theme
- `apps/docs`  → `@import "@astrojs/starlight-tailwind"` + theme, then remap
                 Starlight's `--color-accent-*` / `--color-gray-*` → our brand in `@theme`
- `apps/app`   → `@import "tailwindcss"` + `tw-animate-css` + theme, then map
                 shadcn's `--primary/--background/…` → our brand vars in `@theme inline`

Change one `--color-brand-*` → all three regenerate. Landing/docs stay zero-JS;
dashboard uses React islands (`@astrojs/react`) for state (keys, quota, billing, admin).

**Why Starlight theming this way (the safe pattern):** map ONLY Starlight's accent +
gray scales through `@theme`. NEVER hand-override the polarity/contrast anchors
(`--sl-color-white/black`, `-text-invert`, `-bg-accent`) — that produced the earlier
"defect on the look" (NOTES §4). The `@astrojs/starlight-tailwind` compat layer also
wires dark mode + prevents Preflight from clobbering Starlight's reset.

**LATEST STACK (verified, all 200):**
- astro **7.3.8** · @astrojs/starlight **0.42.6** · @astrojs/starlight-tailwind **5.0.0**
- tailwindcss / @tailwindcss/vite **4.3.3** · react **19.3.1** · @astrojs/react **7.0.1**
- lucide-react 1.57.0 · tw-animate-css 1.4.0 · @radix-ui/react-slot 1.5.0

> Starlight 0.42 breaking change: `{ label, autogenerate }` removed → use
> `{ label, items: [{ autogenerate: { directory } }] }`.

Proof (§7b): `#4338ca` indigo compiles into all three dists (web `bg-brand-700`,
app shadcn `--primary`, docs Starlight accent). `KeyPanel.tsx` island (`client:load`,
shadcn Card + lucide icons) hydrates on the dashboard.

## 3b. Theme Toggle — ONE system, whole domain (2026-10-14)

**Contract (matches Starlight, so they stay in sync):**
- attribute `data-theme` on `<html>` (`light` | `dark`) · storage key `starlight-theme`
- default = OS `prefers-color-scheme`, explicit choice wins; no FOUC (inline
  script applies theme before paint).

**Shared pieces in `packages/ui`:**
- `src/theme.ts` — controller: `getPreferredTheme/applyTheme/toggleTheme/syncToggles/initTheme`
- `src/components/ThemeScript.astro` — `<head>` anti-FOUC init (all surfaces)
- `src/components/ThemeToggle.astro` — one button (`data-theme-toggle`, lucide sun/moon), self-inits

**How each surface themes:**
- Landing + dashboard use our `ThemeToggle` (web nav, app topbar).
- Docs uses **Starlight's own toggle** — already shares the same attr+key, so
  it syncs automatically (no custom toggle there).
- Tokens are **semantic** and flip on `[data-theme="dark"]`; `@theme inline`
  exposes them as utilities (`bg-canvas`, `text-ink`, `bg-accent`, `border-hairline`…).
  shadcn's `--primary/--background/…` map to the SAME semantic vars, so the
  dashboard flips too. Starlight accent/gray map to semantic vars as well.

Verified: build exit 0; dark vars compiled (`[data-theme=dark]{--canvas:#0c0a09;--accent:#818cf8}`);
toggle handler + colorScheme sync bundled; all routes 200. Change one `--accent`
in `theme.css` → whole domain re-themes light AND dark.

## 3c. Starlight re-brand — the cascade gotcha (FIXED 2026-10-14)

**Symptom:** docs kept Starlight's default blue despite mapping `--color-accent-*`.

**Root cause (verified in compiled CSS):** `@astrojs/starlight-tailwind` sets
`--sl-color-*` inside Tailwind's `@layer utilities`. But Starlight declares
`@layer starlight.base,…,starlight.utils` (a NAMED-layer statement), while
Tailwind's `utilities` layer is UNDECLARED. Per CSS spec, **named layers always
outrank undeclared layers regardless of source order** → the plugin's
`@layer utilities` values LOSE to Starlight's own `--sl-color-*` defaults in
`@layer starlight.base`. (Also: plain `:root` literals + `@theme` scale overrides
got dropped/overridden in the build.)

**Fix:** set `--sl-color-*` as **UNLAYERED** rules on `:root` (light) and
`[data-theme='dark']` (dark). Unlayered rules beat EVERY `@layer`, so they win,
and they flip with the one domain-wide toggle. Override ONLY the themeable
subset (accent + gray-1..7); **never** `--sl-color-white/black` (polarity
anchors). Use literal hex (not `@theme` refs) so the build preserves them.

Verified via headless-Chrome screenshot of the live `/docs/`: sidebar renders
our warm stone-dark `#23262f` (not Starlight blue-gray) and accent pixels are
indigo `#818cf8` family. Both `--sl-color-accent: #4338ca` (light) and
`#818cf8` (dark) present unlayered in `common.*.css`.

---

## 4. Tokens (the brand contract — only shared global file)

Grounded in Infisical's measured system — we copy the **caliber** (typographic
discipline, engineering-first crispness), NOT the **identity** (their yellow,
black/white, zero-radius). Colors + radius are OURS and UNIQUE (see 4b).

### 4a. Typography — LOCKED (mirror Infisical's discipline)

One geometric sans for display + body (no pairing). Alliance is licensed →
we use a free equivalent: **Inter** (or Geist/Satoshi) as `--brand-font`.
Tight NEGATIVE tracking on headlines is the "professional" tell.

| token        | size | weight | tracking  | line-height |
|--------------|------|--------|-----------|-------------|
| display-xl   | 56px | 500    | -1.12px   | 1.1         |
| display-lg   | 46px | 600    | -1.38px   | 1.05        |
| heading      | 26px | 500    | -0.52px   | 1.1         |
| body         | 16px | 400    | normal    | 1.5         |
| button/small | 14px | 400    | normal    | 1.5         |

```css
:root {
  /* type */
  --brand-font: 'Inter', system-ui, sans-serif;
  --brand-mono: ui-monospace, Menlo, Consolas, monospace;

  /* spacing (mirror Infisical scale) */
  --space-xxs: 4px;  --space-xs: 8px;  --space-s: 10px;
  --space-sm: 12px;  --space-md: 14px; --space-lg: 18px; --space-xl: 24px;

  /* PALETTE — UNIQUE to UTME Lab, NOT Infisical. v1 proposal below (4b). */
  --brand-bg: #fafaf9;          /* warm off-white canvas (softer than pure white) */
  --brand-ink: #111113;         /* near-black ink */
  --brand-body: #52525b;        /* body text */
  --brand-muted: #737373;
  --brand-hairline: #e4e4e7;    /* 1px borders */
  --brand-accent: #4338ca;      /* deep indigo primary — LOCKED (see 4b) */
  --brand-accent-ink: #eef2ff;
  --brand-surface: #ffffff;

  /* semantic */
  --brand-success: #15803d;
  --brand-warning: #a16207;
  --brand-danger: #dc2626;

  /* radius — UNIQUE. Infisical is zero-radius; ours is soft-modern (confirm 4b) */
  --brand-radius: 8px;          /* soft-modern — LOCKED (see 4b) */
}
```

Every app imports `tokens.css` and NOTHING else global. Docs maps `sl-*` → these vars.

### 4b. Identity — LOCKED (friendly-modern SaaS)

Infisical = zero radius + yellow #f5f841 + pure white/black. We diverge on purpose.

- **Accent:** deep indigo `#4338ca` (ink `#eef2ff`)
- **Radius:** soft-modern **8px** (cards, buttons, inputs) — the "friendly SaaS" tell
- **Canvas:** warm off-white `#fafaf9` (softer than Infisical's pure white)
- **Dark mode:** semantic tokens above are dark-ready; ship **LIGHT-first**, dark later
  = a `[data-theme="dark"]` variable swap (no refactor).

---

## 5. openapi.json (docs reference, no Mintlify)

- Rust owns the contract: `utoipa` in `utmelab-api/src/api/openapi.rs` → `GET /openapi.json`.
- Phase gate emits it: `cargo run -- openapi --out site/ref/site/apps/docs/src/assets/openapi.json`.
- Docs consumes it via `starlight-openapi` plugin (guides hand-written `.md`, reference
  generated). Still 100% static.
- `starlight-openapi@0.27.0` needs `astro>=7.0.2`, `@astrojs/starlight>=0.41.0` — fits Node 22.

```js
// apps/docs/astro.config.mjs
starlight({
  base: '/docs',
  plugins: [starlightOpenAPI([{ base: 'api', schema: './src/assets/openapi.json' }])],
})
```

---

## 6. Same domain now → separate later (zero rewrite)

Now — one build, one Caddy root:
```bash
npm run build   # builds web + docs + app, merges to dist/
# dist/index.html | dist/docs/* | dist/dashboard/*
```
```caddy
api.utmelab.com {
  handle /api/*      { reverse_proxy 127.0.0.1:8081 }
  handle /health     { reverse_proxy 127.0.0.1:8081 }
  handle /openapi.json { reverse_proxy 127.0.0.1:8081 }
  handle { root * .../site; try_files {path} {path}/index.html; file_server }
}
```

Later — same code, 3 static outputs (each app already has its own `base`, so no rewrites):
- `utmelab.com`      ← apps/web/dist
- `docs.utmelab.com` ← apps/docs/dist
- `app.utmelab.com`  ← apps/app/dist

Only DNS + Caddy change. No app imports another app → detach is trivial.

---

## 7. Detach Test

> If you can delete `apps/app` and `apps/web` still builds → the boundary is correct.

## 7b. PROOF — theory validated (built & served)

Scaffolded and verified on 2026-10-14. `npm run build` exits 0, one merged `dist/`:

- `/`             → landing (MarketingLayout) — **200**
- `/docs/`        → docs (Starlight)           — **200**
- `/docs/guides/quickstart/`                    — **200**
- `/dashboard/`   → dashboard (AppShell, distinct `<h1 class="sec">`) — **200**

Detach test (§7): removed `apps/app`, `apps/web` built alone (exit 0) → boundary correct.
Shared lever: all three import `@utmelab/ui/tokens.css` + `Card`/`Button`; none imports another's shell.

> NOTES on what's real vs stubbed: UI kit is real (tokens + Button + Card). web/docs/app
> shells are real and styled. openapi.json + starlight-openapi is intentionally NOT wired
> yet (kept the proof build green). Only quickstart guide + dashboard overview exist.

---

## 8. Build Order (when we flip to Act)

1. `packages/ui/` FIRST — tokens + primitives. Nothing else until this merges.
2. `apps/web/` — MarketingLayout + `/`, `/pricing`, `/terms`. Prove brand w/o docs.
3. `apps/docs/` — Starlight `base:'/docs'` + 2 guide stubs + openapi plugin.
4. `apps/app/` — AppShell + dashboard + signin, NO Starlight import.
5. Merge script + Caddy try_files. `npm run build && preview` serves all 3 from one dist/.

---

## 9. Assumptions

- Stay Astro **static** (best fit for content + islands later). No SSR/Node runtime.
- Dashboard = static HTML calling Axum API (`/api/v1/*`, `/internal/*`); hydrates later.
- Docs search = Pagefind, scoped to `/docs` only.
- Same domain now (`api.utmelab.com` serves all), split later by DNS only.

---

## 10. Open Questions

- ~~Brand palette~~ → LOCKED (indigo #4338ca, off-white #fafaf9). See §4b.
- ~~Dark mode now or later~~ → LOCKED: light-first, dark later (tokens dark-ready). See §4b.
- ~~shadcn vs Astro-native kit~~ → LOCKED: Astro-native kit (§3). (If user later wants
  shadcn, it's a deliberate override — React runtime cost + fights Starlight.)
- Pricing tiers copy + naira amounts — NOT YET (defer until product exists).
- Interactive API playground in-scope for v1, or generated reference only? — OPEN.
- Inter vs Geist/Satoshi as the free Alliance swap — OPEN (default Inter).
