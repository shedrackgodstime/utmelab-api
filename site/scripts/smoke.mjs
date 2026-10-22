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
    return {
      status: res.status,
      contentType: res.headers.get('content-type') || '',
      cacheControl: res.headers.get('cache-control') || '',
      body,
    };
  } catch (e) {
    return { status: 0, contentType: '', cacheControl: '', body: '', networkError: e.cause?.code || e.message };
  } finally {
    clearTimeout(timer);
  }
}

// POST variant, only used to prove the MCP surface is proxied. The transport
// is Streamable HTTP, so the accept header offers both shapes.
async function post(path, body) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const res = await fetch(BASE + path, {
      method: 'POST',
      redirect: 'manual',
      signal: ctrl.signal,
      headers: {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
      },
      body,
    });
    const text = await res.text();
    return { status: res.status, contentType: res.headers.get('content-type') || '', body: text };
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
  // Retry budget is overridable so the same script serves two callers with
  // opposite needs: a deploy is booting a replica and should wait it out
  // (default 18 x 10 s = 180 s), while a scheduled uptime check wants to know
  // NOW and not sit in a retry loop for three minutes. Defaults are unchanged.
  const tries = Number(process.env.SMOKE_READY_TRIES || 18);
  const delay = Number(process.env.SMOKE_READY_DELAY_MS || 10000);
  let ready;
  for (let attempt = 1; attempt <= tries; attempt++) {
    ready = await get('/ready');
    if (!ready.networkError && ready.status === 200) break;
    if (attempt === tries) break;
    await new Promise((resolve) => setTimeout(resolve, delay));
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

  // The MCP surface is keyed like `/api/v1`, so an anonymous POST is a JSON 401
  // from the binary. It is the easiest surface to lose at the edge: there is no
  // static file at /mcp, so a missing reverse_proxy answers Caddy's own
  // empty-body 404, which reads like "no such route" and shipped silently.
  // An empty 404 is the tell; a JSON 401 is the binary refusing the key.
  const mcp = await post('/mcp', '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}');
  if (mcp.networkError) return fail(`/mcp unreachable (${mcp.networkError})`);
  if (mcp.status === 404 && mcp.body === '') {
    return fail('/mcp is 404 with an empty body (Caddy is not proxying /mcp to the binary)');
  }
  if (mcp.status !== 401) return fail(`/mcp without key is ${mcp.status}, want 401`);
  ok('/mcp reaches the binary (401 without key)');

  const mcpAdmin = await post('/mcp/admin', '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}');
  if (mcpAdmin.networkError) return fail(`/mcp/admin unreachable (${mcpAdmin.networkError})`);
  if (mcpAdmin.status === 404 && mcpAdmin.body === '') {
    return fail('/mcp/admin is 404 with an empty body (Caddy is not proxying /mcp to the binary)');
  }
  if (mcpAdmin.status !== 401) return fail(`/mcp/admin without key is ${mcpAdmin.status}, want 401`);
  ok('/mcp/admin reaches the binary (401 without key)');
});

// 2. The discovery surface is open. It is the only unkeyed part of `/api/v1`,
// so both failure modes are loud: a stray gate turns it into a 401 (the
// funnel goes dark) and a widened payload starts leaking bank rows. Neither
// is visible from the keyed routes, hence an assertion of its own.
await group('discovery surface is open', async () => {
  const summary = await get('/api/v1/public/summary');
  if (summary.networkError) return fail(`/api/v1/public/summary unreachable (${summary.networkError})`);
  if (summary.status === 401) return fail('/api/v1/public/summary is 401: the funnel is gated');
  if (summary.status !== 200) return fail(`/api/v1/public/summary status ${summary.status}`);
  let totals;
  try {
    totals = JSON.parse(summary.body);
  } catch {
    return fail('/api/v1/public/summary is not JSON');
  }
  for (const key of ['exams', 'subjects', 'held', 'verified']) {
    if (typeof totals[key] !== 'number') return fail(`/api/v1/public/summary.${key} is ${typeof totals[key]}, want a number`);
  }
  if (totals.verified > totals.held) return fail(`/api/v1/public/summary verified ${totals.verified} exceeds held ${totals.held}`);
  ok(`/api/v1/public/summary is open (${totals.exams} exams, ${totals.subjects} subjects, ${totals.held} held, ${totals.verified} verified)`);

  const exams = await get('/api/v1/public/exams');
  if (exams.status !== 200) return fail(`/api/v1/public/exams status ${exams.status}`);
  // A funnel page must not cost a read per view. The directive is part of the
  // contract, so a cacheable public surface is asserted, not assumed.
  const cache = exams.cacheControl;
  if (!cache.includes('max-age=')) return fail(`/api/v1/public/exams cache-control is ${JSON.stringify(cache)}`);
  ok(`/api/v1/public/exams is cacheable (${cache})`);
  let list;
  try {
    list = JSON.parse(exams.body);
  } catch {
    return fail('/api/v1/public/exams is not JSON');
  }
  if (!Array.isArray(list) || list.length === 0) return fail('/api/v1/public/exams is not a non-empty array');
  // Coarseness at the edge, mirroring the Rust key-set test: the keyless
  // payload is identity and counts. A question id or stem arriving here is a
  // contract break, not a nicety.
  const allowed = ['code', 'countries', 'duration_minutes', 'held', 'name', 'status', 'subjects', 'verified'];
  const extra = Object.keys(list[0]).filter((key) => !allowed.includes(key));
  if (extra.length) return fail(`/api/v1/public/exams grew fields a keyless caller may read: ${extra.join(', ')}`);
  if (!Array.isArray(list[0].subjects)) return fail('/api/v1/public/exams[0].subjects is not an array');
  ok(`/api/v1/public/exams is open (${list.length} exams)`);
});

// 3. Docs serve distinct pages (not one homepage four times).
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

// 4. Misses miss, and extensionless URLs redirect instead of 200ing.
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
