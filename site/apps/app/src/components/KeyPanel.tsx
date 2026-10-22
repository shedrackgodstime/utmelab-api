import { useState } from 'react';
import { Copy, RefreshCw, Check } from 'lucide-react';
import { Button } from './ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from './ui/card';

/**
 * Real interactive React island (client:load). Proves the dashboard carries
 * genuine app behavior — state, actions, DOM. Later: calls the Axum API.
 */
export default function KeyPanel() {
  const [key, setKey] = useState('utme_live_sk_9f2a••••••••••••••••3f9a');
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  async function rotate() {
    setBusy(true);
    await new Promise((r) => setTimeout(r, 500)); // later: POST /api/v1/keys/rotate
    const rand = Math.random().toString(36).slice(2, 6);
    setKey(`utme_live_sk_${rand}••••••••••••••••${rand}`);
    setBusy(false);
    setCopied(false);
  }

  async function copy() {
    try { await navigator.clipboard.writeText(key); } catch { /* ignore */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Live API key</CardTitle>
        <CardDescription>Rotate instantly if it leaks. The old key stops working immediately.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-2">
          <code className="flex-1 overflow-x-auto rounded-md border bg-muted px-3 py-2 font-mono text-sm">{key}</code>
          <Button variant="secondary" onClick={copy} type="button">
            {copied ? <Check /> : <Copy />}
            {copied ? 'Copied' : 'Copy'}
          </Button>
          <Button onClick={rotate} type="button" disabled={busy}>
            <RefreshCw className={busy ? 'animate-spin' : undefined} />
            {busy ? 'Rotating…' : 'Rotate key'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
