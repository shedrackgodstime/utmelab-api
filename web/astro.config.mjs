// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';

// The web tier is **static files only** (dev_docs/QUESTION_BANK_DECISIONS.md D32).
// No adapter: nothing here runs a server. Caddy path-routes `/api/*` to the Rust
// binary and everything else to the built output of this project.
//
// Docs live under /docs so the Starlight index and an Astro landing page do not
// both claim `/`.
export default defineConfig({
	site: 'https://api.utmelab.com',
	base: '/docs',
	trailingSlash: 'always',
	integrations: [
		starlight({
			title: 'UTME Lab API',
			description:
				'JAMB, WAEC and NECO past questions, syllabus and answers. Keyed to ' +
				'subtopics so a weak spot is a twenty-question sitting, not a paper.',
			social: [],
			customCss: ['./src/styles/app.css'],
			editLink: undefined,
			lastUpdated: true,
			sidebar: [
				{
					label: 'Start',
					items: [
						{ label: 'Introduction', slug: '' },
						{ label: 'Authentication', slug: 'guides/authentication' },
						{ label: 'Pagination', slug: 'guides/pagination' },
						{ label: 'Errors', slug: 'guides/errors' },
					],
				},
				{
					label: 'Guides',
					items: [
						{ label: 'Finding questions', slug: 'guides/finding-questions' },
						{ label: 'Syllabus and coverage', slug: 'guides/syllabus' },
					],
				},
				// API reference, generated from openapi.json (D31).
				...openAPISidebarGroups,
			],
			plugins: [
				starlightOpenAPI([
					{
						base: 'api',
						// A **file**, not the live URL: the build stays deterministic
						// and does not need the API running. Refresh with `bun run spec`.
						schema: './openapi.json',
					},
				]),
			],
		}),
	],
});