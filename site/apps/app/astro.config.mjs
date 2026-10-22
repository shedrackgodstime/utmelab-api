// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import tailwindcss from '@tailwindcss/vite';

// DASHBOARD surface. Astro shell + React islands (scoped HERE only) + Tailwind v4.
// Real shadcn components live in src/components/ui. React does NOT touch docs/landing.
// base '/dashboard' + static → detachable to app.utmelab.com with zero rewrite.
export default defineConfig({
  site: 'https://api.utmelab.com',
  base: '/dashboard',
  output: 'static',
  build: { format: 'directory' },
  integrations: [react()],
  vite: { plugins: [tailwindcss()], build: { cssMinify: 'esbuild' } },
});

