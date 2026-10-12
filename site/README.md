# site — the UTME Lab API website

One Astro project, three surfaces:

| Route | Built from | Serves |
|---|---|---|
| `/` | `src/pages/index.astro` | landing + first call |
| `/docs/…` | `src/content/docs/docs/` | Starlight (guides + generated OpenAPI reference) |
| `/dashboard/…` | `src/pages/dashboard/` | daisyUI shell — **scaffolded, not built** |
| `/signin/`, `/signup/`, `/reset-password/` | `src/pages/*` | daisyUI auth cards — **scaffolded, not built** |

## Working on it

```bash
npm ci
npm run dev            # or: ./serve.sh to preview a build
npm run build
```

### Termux only

Three upstream packages ship no Android build, so `./build.sh` works around them
and `npm run build` does not:

- `satteri` → WASI build (`@bruits/satteri-android-arm64` is a 404 on npm)
- `sharp` → WASI build (`@img/sharp-android-arm64` is a 404 on npm)
- `pagefind` → static musl binary (no android-arm64 npm package)

`build.sh` also re-applies a WASI preopen patch that any `npm install` reverts.
CI and the VPS have native linux bindings and run plain `npm ci && npm run build`.

## Before you start

| file | what it tells you |
|---|---|
| `docs/DASHBOARD.md` | the dashboard is scaffolded; what is decided, what is not, what is next |
| `openapi.json` | generated — `cargo run -- openapi --out site/openapi.json`. Never hand-edit |

## Conventions

- **Docs live one level deep.** `src/content/docs/docs/` is what makes Starlight
  serve from `/docs`. Every sidebar `slug` and the OpenAPI plugin's `base` carry
  the `docs/` prefix. Astro's global `base` is deliberately **not** used.
- **`dashboard.css` is imported by the two layouts only** (`Dashboard.astro`, `Auth.astro`). daisyUI themes
  `:root`, and Tailwind preflight is excluded, so the docs are never repainted.
- **Design tokens are not yet unified** — three systems exist. Fixing that is
  item 1 in `docs/DASHBOARD.md`.
