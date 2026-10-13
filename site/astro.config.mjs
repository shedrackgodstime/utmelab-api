// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://api.utmelab.com',
	integrations: [
		starlight({
			title: 'UTME Lab',
			customCss: [
				'./src/styles/theme.css',
				'./src/styles/dash-frame.css',
				'./src/styles/auth-frame.css',
				'./src/styles/no-toc.css',
			],
			components: {
				Header: './src/overrides/Header.astro',
				PageFrame: './src/overrides/PageFrame.astro',
				Sidebar: './src/overrides/Sidebar.astro',
				Pagination: './src/overrides/Pagination.astro',
				MobileMenuToggle: './src/overrides/MobileMenuToggle.astro',
				PageTitle: './src/overrides/PageTitle.astro',
				Search: './src/overrides/Search.astro',
			},
			sidebar: [
				{ label: 'Introduction', link: '/' },
				{ label: 'Pricing', slug: 'pricing' },
				{
					label: 'Getting started',
					collapsed: true,
					items: [
						{ label: 'Quickstart', slug: 'guides/quickstart' },
						{ label: 'Authentication', slug: 'guides/authentication' },
						{ label: 'Rate limits', slug: 'guides/rate-limits' },
						{ label: 'Pagination', slug: 'guides/pagination' },
						{ label: 'Errors', slug: 'guides/errors' },
					]
				},
				{
					label: 'Guides',
					collapsed: true,
					items: [
						{ label: 'Browsing the catalog', slug: 'guides/catalog' },
						{ label: 'Finding questions', slug: 'guides/finding-questions' },
						{ label: 'Syllabus and coverage', slug: 'guides/syllabus' },
						{ label: 'Passages and novels', slug: 'guides/passages-novels' },
						{ label: 'Reporting issues', slug: 'guides/reporting-issues' },
						{ label: 'Managing your key', slug: 'guides/managing-your-key' },
					],
				},
				{
					label: 'Legal',
					collapsed: true,
					items: [
						{ label: 'Terms of Service', slug: 'terms' },
						{ label: 'Privacy Policy', slug: 'privacy' },
					],
				},
			],
		}),
	],
});
