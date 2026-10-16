/* Only public external provider IO is replaced. Auth, quotas, location/scoring SQL
 * and the Worker run normally. Loaded solely by the Playwright dev-server process. */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
/* global URL, Response */
const fixtures = JSON.parse(readFileSync(fileURLToPath(new URL('./fixtures/addresses.json',import.meta.url)), 'utf8'));
// Synthetic EPSG:5179 inverse projections of the frozen test points, prepared by
// snapshot.py. Not actual Juso responses, and no stored legacy fixture is rewritten.
const coordinates = JSON.parse(readFileSync(fileURLToPath(new URL('../../.local/e2e-juso-coordinates.json',import.meta.url)), 'utf8'));
const original = globalThis.fetch;
globalThis.fetch = async function(input, init) {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  if (url.hostname === 'business.juso.go.kr') {
    const isCoordinate = url.pathname === '/addrlink/addrCoordApi.do';
    const fixture = fixtures.find(f => isCoordinate
      ? ['admCd','rnMgtSn','udrtYn','buldMnnm','buldSlno'].every(k=>f.selection[k]===url.searchParams.get(k))
      : f.address === url.searchParams.get('keyword'));
    if (!fixture) throw new Error('E2E address not in approved public fixtures');
    const body = isCoordinate ? { results: { common: { errorCode:'0', totalCount:'1' },
      juso:[{ bdMgtSn:fixture.selection.bdMgtSn, ...coordinates[fixture.selection.bdMgtSn] }] } } : fixture.search_response;
    return new Response(JSON.stringify(body), { headers: { 'Content-Type':'application/json' } });
  }
  if (!['127.0.0.1','localhost','::1'].includes(url.hostname)) throw new Error('E2E cannot call external services');
  return original(input, init);
};
