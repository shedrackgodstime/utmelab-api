## Development

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

## Shell rules (one Starlight shell, three surfaces)

- Precedence for any change: Starlight config first, scoped CSS second,
  content components third, new component override last. A new override
  needs justification and must delegate to `<Default />` everywhere but
  its own routes. Current overrides (hold at five): PageFrame, Sidebar,
  Pagination, MobileMenuToggle, PageTitle.
- `@astrojs/starlight` is pinned exact in package.json. Review its
  changelog before any bump; overrides copy its internals and can stale.
  Current overrides (seven): PageFrame, Sidebar, Pagination,
  MobileMenuToggle, PageTitle, Search (verbatim upstream copy + section
  scoping only), Header (verbatim upstream copy + site nav + auth
  placeholder only).
- Dashboard geometry lives under `.dash-frame` in
  `src/styles/dash-frame.css` only. Nothing global, ever.
- New-page frontmatter checklist:
  - docs pages: nothing extra.
  - dashboard pages (`dashboard/*`): `tableOfContents: false`.
    They are search-indexed under the `dashboard` section filter.
  - auth pages (`signin`, `signup`, `reset-password`, `verify-email`):
    `template: splash` + `pagefind: false`.
- Search sections come from `data-pagefind-filter` spans in
  `src/overrides/PageFrame.astro` (`docs` vs `dashboard`). Pagefind
  shows them as result filters automatically.
- Dashboard nav has one source: `src/overrides/Sidebar.astro`. The
  sidebar config in `astro.config.mjs` is docs-only.
- Content truth (v1): keys are CLI-issued, no self-serve accounts until
  Phase 2 — docs must never promise self-serve keys. `/health` belongs
  as a monitoring section inside Errors, not its own page.

## Documentation

Full documentation: https://docs.astro.build

Consult these guides before working on related tasks:

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Using React, Vue, Svelte, or other framework components](https://docs.astro.build/en/guides/framework-components/)
- [Adding or managing content](https://docs.astro.build/en/guides/content-collections/)
- [Adding styles or using Tailwind](https://docs.astro.build/en/guides/styling/)
- [Supporting multiple languages](https://docs.astro.build/en/guides/internationalization/)
