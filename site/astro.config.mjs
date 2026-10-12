// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://api.utmelab.com',
	integrations: [
		starlight({
			title: 'UTME Lab',
			customCss: ['./src/styles/dash-frame.css', './src/styles/auth-frame.css'],
			components: {
				PageFrame: './src/overrides/PageFrame.astro',
				Sidebar: './src/overrides/Sidebar.astro',
				Pagination: './src/overrides/Pagination.astro',
				MobileMenuToggle: './src/overrides/MobileMenuToggle.astro',
				PageTitle: './src/overrides/PageTitle.astro',
				Search: './src/overrides/Search.astro',
			},
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
			],
		}),
	],
});
