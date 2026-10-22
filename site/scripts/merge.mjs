// Merge the three static builds into ONE dist/ so Caddy serves
// / + /docs/* + /dashboard/* off a single domain (NOTES §6).
// Each app already has its own `base`, so no path rewriting is needed.
import { cpSync, rmSync, mkdirSync, copyFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const dist = join(root, 'dist');

const apps = [
  { name: 'web',   out: join(root, 'apps/web/dist'),   into: '' },
  { name: 'docs',  out: join(root, 'apps/docs/dist'),  into: 'docs' },
  { name: 'app',   out: join(root, 'apps/app/dist'),   into: 'dashboard' },
];

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });

for (const app of apps) {
  const target = join(dist, app.into);
  mkdirSync(target, { recursive: true });
  cpSync(app.out, target, { recursive: true });
  console.log(`merged apps/${app.name} -> dist/${app.into}`);
}
console.log(`\nOK. Single static site at ${dist}`);
console.log('  /           <- landing');
console.log('  /docs/*     <- docs');
console.log('  /dashboard/*<- dashboard');

// The committed spec ships at /openapi.json so footer + quickstart links
// resolve on the static host, not only against the API binary.
const spec = join(root, 'openapi.json');
if (existsSync(spec)) {
  copyFileSync(spec, join(dist, 'openapi.json'));
  console.log('  /openapi.json <- committed spec');
} else {
  console.warn('WARN: site/openapi.json missing — run `UPDATE_SPEC=1 cargo test --lib openapi` at the repo root');
}
