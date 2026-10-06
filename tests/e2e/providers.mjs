/* Only public external provider IO is replaced. Auth, quotas, location/scoring SQL
 * and the Worker run normally. Loaded solely by the Playwright dev-server process. */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
/* global URL, Response */
const fixtures = JSON.parse(readFileSync(fileURLToPath(new URL('./fixtures/addresses.json',import.meta.url)), 'utf8'));
const original = globalThis.fetch;
globalThis.fetch = async function(input, init) {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  if (url.hostname === 'business.juso.go.kr' || url.hostname === 'api.vworld.kr') {
    const query = url.searchParams.get('keyword') || url.searchParams.get('address');
    const fixture = fixtures.find(f => f.address === query);
    if (!fixture) throw new Error('E2E address not in approved public fixtures');
    const body = url.hostname === 'business.juso.go.kr' ? fixture.search_response : fixture.coordinate_response;
    return new Response(JSON.stringify(body), { headers: { 'Content-Type':'application/json' } });
  }
  if (!['127.0.0.1','localhost','::1'].includes(url.hostname)) throw new Error('E2E cannot call external services');
  return original(input, init);
};
