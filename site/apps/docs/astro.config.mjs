// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';
import tailwindcss from '@tailwindcss/vite';

// DOCS surface. Astro + Starlight + Tailwind v4 (Starlight compat layer).
// We theme Starlight through Tailwind @theme → its accent/gray vars, so docs
// share ONE brand with landing + dashboard. base '/docs' + static.
//
// Reference pages generate at build time from site/openapi.json, which is
// generated from the handlers and checked in (never hand edited): run
// `UPDATE_SPEC=1 cargo test --lib openapi` to regenerate it. Sidebar rule
// lives in site/docs/docs-IA-PLAN.md.
export default defineConfig({
  site: 'https://api.utmelab.com',
  base: '/docs',
  output: 'static',
  build: { format: 'directory' },
  vite: { plugins: [tailwindcss()], build: { cssMinify: 'esbuild' } },
  integrations: [
    starlight({
      title: 'UTME Lab',
      description: 'Structured JAMB, WAEC and NECO content over one API.',
      customCss: ['./src/styles/theme.css'],
      plugins: [
        starlightOpenAPI([
          {
            base: 'reference',
            schema: '../../openapi.json',
            sidebar: {
              label: 'API Reference',
              collapsed: true,
              operations: { badges: true },
            },
          },
        ]),
      ],
      sidebar: [
        { label: 'Introduction', link: '/' },
        { label: 'Quickstart', slug: 'guides/quickstart' },
        {
          label: 'Guides',
          collapsed: true,
          items: [{ autogenerate: { directory: 'guides/catalog' } }],
        },
        ...openAPISidebarGroups,
      ],
    }),
  ],
});
