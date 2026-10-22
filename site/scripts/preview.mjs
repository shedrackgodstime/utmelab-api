// Zero-dependency static preview for the merged dist/.
// Serves / , /docs/* , /dashboard/* exactly as Caddy will (NOTES §6).
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, extname, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const distDir = join(root, 'dist');
const port = Number(process.env.PORT || 4321);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

async function resolve(urlPath) {
  let p = decodeURIComponent(urlPath.split('?')[0]);
  if (p.endsWith('/')) p += 'index.html';
  let file = join(distDir, normalize(p));
  if (!file.startsWith(distDir)) return null; // block traversal
  try {
    const s = await stat(file);
    if (s.isDirectory()) file = join(file, 'index.html');
  } catch {
    // try {path}/index.html then fall back to root index
    const alt = join(distDir, normalize(p), 'index.html');
    try { await stat(alt); file = alt; } catch { return null; }
  }
  return file;
}

createServer(async (req, res) => {
  const file = await resolve(req.url || '/');
  if (!file) { res.writeHead(404); res.end('not found'); return; }
  try {
    const body = await readFile(file);
    res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
    res.end(body);
  } catch {
    res.writeHead(404); res.end('not found');
  }
}).listen(port, () => {
  console.log(`preview: http://localhost:${port}`);
  console.log(`  /          ${port}  (landing)`);
  console.log(`  /docs/     ${port}  (docs)`);
  console.log(`  /dashboard/ ${port}  (dashboard)`);
});
