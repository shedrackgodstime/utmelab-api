// Site-wide lint: Astro pages + JS/MJS + TS/TSX (React islands).
// Zero-warning policy: deploy runs `npm run lint` as a release gate.
import js from '@eslint/js';
import astro from 'eslint-plugin-astro';
import ts from 'typescript-eslint';
import globals from 'globals';

export default [
  { ignores: ['**/dist/**', '**/node_modules/**', '**/.astro/**'] },
  js.configs.recommended,
  ...ts.configs.recommended,
  ...astro.configs['flat/recommended'],
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
];
