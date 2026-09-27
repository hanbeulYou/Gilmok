/** Local Chrome smoke proof; full Playwright product flows start in S3-2. */
/* global WebSocket, fetch, setTimeout, clearTimeout, URL */
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import process from "node:process";

const [url, output, chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"] = process.argv.slice(2);
if (!url || !output || !["localhost", "127.0.0.1"].includes(new URL(url).hostname)) throw new Error("Local URL and output required");
const profile = await mkdtemp(join(tmpdir(), "gilmok-compare-"));
const browser = spawn(chrome, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run", "about:blank"], { stdio: "ignore" });
let socket;
const timeout = setTimeout(() => browser.kill(), 90000);
try {
  let port;
  for (let i = 0; i < 200; i++) {
    try { port = (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0]; break; }
    catch { await delay(50); }
  }
  if (!port) throw new Error("Chrome did not start");
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(pages.find(p => p.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0, signups = 0, calls = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const data = JSON.parse(event.data);
    if (data.method === "Network.requestWillBeSent" && data.params.request.method === "POST") {
      const path = new URL(data.params.request.url).pathname;
      if (path === "/auth/v1/signup") signups++;
      if (path === "/rest/v1/rpc/score_inputs") calls++;
    }
    const request = pending.get(data.id);
    if (!request) return;
    pending.delete(data.id);
    if (data.error) request.reject(new Error("CDP request failed"));
    else request.resolve(data.result);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => (await send("Runtime.evaluate", { expression, returnByValue: true })).result.value;
  const ready = async () => {
    for (let i = 0; i < 200; i++) {
      const result = await evaluate(`(() => {
        const text = document.querySelector('pre')?.textContent;
        return text ? JSON.parse(text).meta.schema_version === '1.3' : false;
      })()`);
      if (result) { await delay(500); return; }
      await delay(100);
    }
    throw new Error("Compare JSON did not render");
  };
  await send("Network.enable");
  await send("Page.enable");
  await send("Page.navigate", { url });
  await ready();
  if (signups !== 1 || calls !== 1) throw new Error("Duplicate sign-in or first-render RPC");
  const sessionId = `JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.endsWith('-auth-token')))).user.id`;
  const first = await evaluate(sessionId);
  await send("Page.reload");
  await ready();
  const second = await evaluate(sessionId);
  if (!first || first !== second || signups !== 1 || calls !== 2) throw new Error("Session reuse failed");
  await writeFile(output, JSON.stringify({ first_render_rpc_calls: 1, anonymous_signups: signups,
    reload_reuses_uid: true, schema_version: "1.3", scope: "local development browser" }, null, 2));
} finally {
  clearTimeout(timeout);
  socket?.close();
  browser.kill();
  await delay(300);
  await rm(profile, { recursive: true, force: true });
}
