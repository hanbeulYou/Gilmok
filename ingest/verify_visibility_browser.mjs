/** Native Chrome + CDP + Node WebSocket: no browser runtime dependency in the app. */
/* global process, WebSocket, fetch, console, setTimeout, clearTimeout, URL */
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
const [url, output, chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'] = process.argv.slice(2);
if (!url || !output || !['localhost', '127.0.0.1'].includes(new URL(url).hostname)) throw new Error('Expected local harness URL and output path');
const profile = await mkdtemp(join(tmpdir(), 'gilmok-visibility-chrome-'));
const browser = spawn(chrome, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', 'about:blank'], { stdio: 'ignore' });
let socket;
const timeout = setTimeout(() => { browser.kill(); }, 90000);
try {
  let port;
  for (let i = 0; i < 200; i++) {
    try { port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; }
    catch { await delay(50); }
  }
  if (!port) throw new Error('Chrome did not start');
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const data = JSON.parse(event.data), request = pending.get(data.id);
    if (!request) return;
    pending.delete(data.id);
    if (data.error) request.reject(new Error(JSON.stringify(data.error))); else request.resolve(data.result);
  };
  socket.onclose = () => { for (const p of pending.values()) p.reject(new Error('Chrome disconnected')); pending.clear(); };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params }));
  });
  await send('Page.enable');
  await send('Page.navigate', { url });
  await delay(300);
  const reply = await send('Runtime.evaluate', { expression: `new Promise((resolve,reject) => {
    const start = Date.now();
    const check = () => {
      if (globalThis.verification) globalThis.verification.then(resolve,reject);
      else if (Date.now()-start > 30000) reject(new Error('Harness did not load'));
      else setTimeout(check,20);
    }; check();
  })`, awaitPromise: true, returnByValue: true });
  if (reply.exceptionDetails) throw new Error(JSON.stringify(reply.exceptionDetails));
  await writeFile(output, JSON.stringify(reply.result.value, null, 2) + '\n');
  console.log('Browser Worker verification saved');
} finally {
  clearTimeout(timeout); socket?.close(); browser.kill();
  await new Promise(resolve => { if (browser.exitCode !== null) resolve(); else browser.once('exit', resolve); });
  await rm(profile, { recursive: true, force: true });
}
