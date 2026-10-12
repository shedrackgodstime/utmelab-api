// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';
import tailwindcss from '@tailwindcss/vite';

// One Astro project, three surfaces:
//
//   /             src/pages/index.astro           marketing + first call
//   /docs/…       src/content/docs/docs/…        Starlight
//   /dashboard/   src/pages/dashboard/index.astro the app
//
// Starlight injects a catch-all `[...slug]` at the site root, so it cannot be
// told to start at /docs. The supported way to move it is a nested directory:
// everything under src/content/docs/docs/ is served one segment deeper. That
// is why every slug and every `base` below carries the `docs/` prefix.
//
// Astro's global `base` is deliberately NOT used. It would prefix the landing
// page and the dashboard too, and it does not rewrite authored markdown links
// — see withastro/starlight#3660. The nested directory needs no such care.
export default defineConfig({
	site: 'https://api.utmelab.com',
	trailingSlash: 'always',
	// Tailwind drives the dashboard's daisyUI blocks only. The generated CSS is
	// imported by src/layouts/Dashboard.astro, never globally, and Tailwind's
	// preflight is deliberately excluded (see src/styles/dashboard.css) so it
	// cannot reset Starlight.
	vite: { plugins: [tailwindcss()] },
	integrations: [
		starlight({
			title: 'UTME Lab',
			description:
				'Past questions for the Nigerian exams, keyed to subtopics so a weak spot is a short sitting, not a whole paper.',
			customCss: ['./src/styles/app.css'],
			// Starlight's Header has no slots, so site nav is a component override.
			components: { Header: './src/components/SiteHeader.astro' },
			editLink: undefined,
			sidebar: [
				{
					label: 'Start',
					items: [
						{ label: 'Introduction', slug: 'docs' },
						{ label: 'Authentication', slug: 'docs/guides/authentication' },
						{ label: 'Pagination', slug: 'docs/guides/pagination' },
						{ label: 'Errors', slug: 'docs/guides/errors' },
					],
				},
				{
					label: 'Guides',
					items: [
						{ label: 'Finding questions', slug: 'docs/guides/finding-questions' },
						{ label: 'Syllabus and coverage', slug: 'docs/guides/syllabus' },
					],
				},
				// Generated from site/openapi.json, which is produced by the API
				// binary: `cargo run -- openapi --out site/openapi.json`.
				...openAPISidebarGroups,
			],
			plugins: [
				starlightOpenAPI([
					{
						// `docs/api` so the reference sits beside the guides instead of
						// at the site root, where it would collide with /dashboard.
						base: 'docs/api',
						// A file, not the live URL: the build stays deterministic and does
						// not need the API running.
						schema: './openapi.json',
						sidebar: {
							// Without this the group is titled from the spec's info.title
							// ("UTME Lab Question Bank API"), which is redundant next to
							// a site already called UTME Lab.
							label: 'API reference',
							operations: { badges: true },
						},
					},
				]),
			],
		}),
	],
});