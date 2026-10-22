// @ts-check
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

// LANDING surface. Pure Astro + Tailwind v4 — NO Starlight.
// Own shell (MarketingLayout). base '/' + static. Detachable to
// utmelab.com with zero rewrite (NOTES §6).
export default defineConfig({
  site: 'https://api.utmelab.com',
  base: '/',
  output: 'static',
  build: { format: 'directory' },
  vite: { plugins: [tailwindcss()], build: { cssMinify: 'esbuild' } },
});
