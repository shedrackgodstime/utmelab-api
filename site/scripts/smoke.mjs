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
  const health = await get('/health');
  if (health.networkError) return fail(`/health unreachable (${health.networkError})`);
  if (health.status !== 200) return fail(`/health status ${health.status}`);
  if (!health.contentType.includes('json')) return fail(`/health is ${health.contentType}, not JSON (static tier is shadowing the API)`);
  let h;
  try {
    h = JSON.parse(health.body);
  } catch {
    return fail('/health body is not JSON');
  }
  for (const key of ['version', 'bank_version', 'subjects', 'questions']) {
    if (h[key] === undefined || h[key] === null) return fail(`/health missing ${key}`);
  }
  ok(`/health ok (v${h.version}, bank ${h.bank_version}, ${h.questions} questions)`);

  const exams = await get('/api/v1/exams');
  if (exams.status !== 200) return fail(`/api/v1/exams status ${exams.status}`);
  if (!exams.body.includes('JAMB')) return fail('/api/v1/exams carries no catalog data');
  ok('/api/v1/exams serves catalog data');

  const anon = await get('/api/v1/questions?exam=JAMB&per_page=1');
  if (anon.status !== 401) return fail(`/api/v1/questions without key is ${anon.status}, want 401`);
  ok('/api/v1/questions is keyed (401 without key)');
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
