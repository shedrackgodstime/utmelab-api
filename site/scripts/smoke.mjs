// Edge smoke check: what the internet actually gets. Run as the last step
// of the deploy job against the public origin (NOT loopback — the point is
// the full path through Caddy, TLS and route resolution).
//
// Why titles, not just statuses: two real outages shipped green because
// every broken route returned 200 with the identical home page. Titles are
// compared as an array — never word-split, titles contain spaces.
//
// Usage: BASE_URL=https://api.utmelab.com node scripts/smoke.mjs
// Exit non-zero on any failure so the deploy run goes red.

const BASE = (process.env.BASE_URL || 'https://api.utmelab.com').replace(/\/+$/, '');

let failures = 0;

function fail(message) {
  failures += 1;
  console.error(`  FAIL ${message}`);
}

function ok(message) {
  console.log(`  ok ${message}`);
}

async function get(path) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const res = await fetch(BASE + path, { redirect: 'manual', signal: ctrl.signal });
    const body = await res.text();
    return { status: res.status, contentType: res.headers.get('content-type') || '', body };
  } catch (e) {
    return { status: 0, contentType: '', body: '', networkError: e.cause?.code || e.message };
  } finally {
    clearTimeout(timer);
  }
}

function titleOf(html) {
  const m = html.match(/<title>([^<]*)<\/title>/i);
  return m ? m[1].trim() : '';
}

async function group(name, fn) {
  console.log(name);
  await fn();
}

// 1. The API reaches the binary (not the static tier).
await group('api reaches the binary', async () => {
  // Readiness is the meaningful signal: 200 only once the replica is open and
  // its schema contract is trusted, so Caddy answers 502 until then. Poll
  // instead of failing the deploy on its own boot time: 18 tries x 10 s.
  let ready;
  for (let attempt = 1; attempt <= 18; attempt++) {
    ready = await get('/ready');
    if (!ready.networkError && ready.status === 200) break;
    if (attempt === 18) break;
    await new Promise((resolve) => setTimeout(resolve, 10000));
  }
  if (ready.networkError) return fail(`/ready unreachable (${ready.networkError})`);
  if (ready.status !== 200) return fail(`/ready status ${ready.status} (replica not open or contract not trusted)`);
  if (ready.contentType.includes('html')) return fail(`/ready is ${ready.contentType} (static tier is shadowing the API)`);
  ok('/ready is up');

  // Liveness is plain text "ok" by design; HTML here means the static tier
  // answered instead of the binary.
  const health = await get('/health');
  if (health.status !== 200) return fail(`/health status ${health.status}`);
  if (health.contentType.includes('html')) return fail(`/health is ${health.contentType} (static tier is shadowing the API)`);
  ok('/health is live');

  // Every `/api/v1` route is key-gated, not just the metered ones. A missing
  // key is a 401 from the key layer, which also proves the request reached the
  // binary: the static tier would answer 404 or HTML.
  const anon = await get('/api/v1/exams');
  if (anon.status !== 401) return fail(`/api/v1/exams without key is ${anon.status}, want 401`);
  ok('/api/v1/exams is keyed (401 without key)');

  // The committed spec is not served by the binary; `merge.mjs` copies it into
  // dist/ so it ships with the static site and the docs reference resolves.
  const spec = await get('/openapi.json');
  if (spec.status !== 200) return fail(`/openapi.json status ${spec.status}`);
  let doc;
  try {
    doc = JSON.parse(spec.body);
  } catch {
    return fail('/openapi.json is not JSON');
  }
  if (!doc.openapi || !doc.paths) return fail('/openapi.json is not an OpenAPI document');
  ok(`/openapi.json ok (${Object.keys(doc.paths).length} paths)`);
});

// 2. Docs serve distinct pages (not one homepage four times).
await group('docs serve distinct pages', async () => {
  const pages = ['/', '/docs/', '/docs/guides/quickstart/', '/dashboard/'];
  const titles = [];
  for (const path of pages) {
    const res = await get(path);
    if (res.networkError) {
      fail(`${path} unreachable (${res.networkError})`);
      continue;
    }
    if (res.status !== 200) {
      fail(`${path} status ${res.status}`);
      continue;
    }
    const title = titleOf(res.body);
    if (!title) {
      fail(`${path} has no <title>`);
      continue;
    }
    titles.push(title);
    ok(`${path} -> ${title}`);
  }
  const unique = new Set(titles);
  if (unique.size !== titles.length) {
    fail(`titles are not distinct: ${JSON.stringify(titles)}`);
  } else if (titles.length === pages.length) {
    ok('all four titles differ');
  }
});

// 3. Misses miss, and extensionless URLs redirect instead of 200ing.
await group('misses and redirects', async () => {
  const missing = await get('/no-such-page-check-' + Date.now());
  if (missing.status !== 404) fail(`missing path is ${missing.status}, want 404`);
  else ok('missing path is 404');

  const bare = await get('/docs/guides/quickstart');
  if (![301, 308].includes(bare.status)) fail(`extensionless docs URL is ${bare.status}, want 301/308`);
  else ok(`extensionless docs URL redirects (${bare.status})`);
});

if (failures > 0) {
  console.error(`\nsmoke: ${failures} failure(s)`);
  process.exit(1);
}
console.log('\nsmoke: all green');
