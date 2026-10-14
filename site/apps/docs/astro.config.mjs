// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

// DOCS surface. Astro + Starlight + Tailwind v4 (Starlight compat layer).
// We theme Starlight through Tailwind @theme → its accent/gray vars, so docs
// share ONE brand with landing + dashboard. base '/docs' + static.
export default defineConfig({
  site: 'https://api.utmelab.com',
  base: '/docs',
  output: 'static',
  build: { format: 'directory' },
  vite: { plugins: [tailwindcss()], build: { cssMinify: 'esbuild' } },
  integrations: [
    starlight({
      title: 'UTME Lab',
      description: 'Engineering-first exam API.',
      customCss: ['./src/styles/theme.css'],
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/Infisical' }],
      sidebar: [
        { label: 'Guides', items: [{ autogenerate: { directory: 'guides' } }] },
      ],
    }),
  ],
});

