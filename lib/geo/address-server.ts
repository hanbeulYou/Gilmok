import type { AddressProvider, AddressSelection, CoordinateOutcome } from './address-provider';

export class AddressError extends Error {
  constructor(public readonly code: string, public readonly status = 502) { super(code); }
}
type Json = Record<string, unknown>;
function obj(value: unknown): Json {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new AddressError('provider_response_invalid');
  return value as Json;
}
function str(value: unknown): string {
  if (typeof value !== 'string') throw new AddressError('provider_response_invalid');
  return value;
}
function digits(value: unknown, pattern: RegExp): string {
  const text = str(value);
  if (!pattern.test(text)) throw new AddressError('provider_response_invalid');
  return text;
}
export function parseSelection(value: unknown): AddressSelection {
  const r = obj(value);
  const admCd = digits(r.admCd, /^\d{10}$/), mtYn = digits(r.mtYn, /^[01]$/);
  const lnbrMnnm = digits(r.lnbrMnnm, /^\d{1,4}$/), lnbrSlno = digits(r.lnbrSlno, /^\d{1,4}$/);
  return { provider: 'juso', admCd, mtYn, lnbrMnnm, lnbrSlno,
    pnu: admCd + (mtYn === '1' ? '2' : '1') + lnbrMnnm.padStart(4, '0') + lnbrSlno.padStart(4, '0'),
    rnMgtSn: digits(r.rnMgtSn, /^\d{12}$/), udrtYn: digits(r.udrtYn, /^[01]$/),
    buldMnnm: digits(r.buldMnnm, /^\d{1,5}$/), buldSlno: digits(r.buldSlno, /^\d{1,5}$/),
    bdMgtSn: digits(r.bdMgtSn, /^\d{25}$/), roadAddrPart1: str(r.roadAddrPart1),
    jibunAddr: str(r.jibunAddr), bdNm: str(r.bdNm ?? ''), rn: str(r.rn),
    sggNm: str(r.sggNm), emdNm: str(r.emdNm) };
}
export function parseSearch(value: unknown): { total: number; choices: AddressSelection[] } {
  const results = obj(obj(value).results), common = obj(results.common);
  if (common.errorCode !== '0') throw new AddressError('juso_search_rejected');
  const total = Number(common.totalCount);
  if (!Number.isSafeInteger(total) || total < 0) throw new AddressError('provider_response_invalid');
  if (total === 0) return { total, choices: [] };
  if (!Array.isArray(results.juso)) throw new AddressError('provider_response_invalid');
  return { total, choices: results.juso.map(parseSelection) };
}
export function parseVworld(value: unknown, selection: AddressSelection): CoordinateOutcome {
  const response = obj(obj(value).response);
  if (response.status === 'NOT_FOUND') return { status: 'not_found', coordinate_provider: 'vworld' };
  if (response.status !== 'OK') throw new AddressError('vworld_coordinate_rejected');
  const result = obj(response.result), point = obj(result.point), structure = obj(obj(response.refined).structure);
  const buildingNumber = Number(selection.buldMnnm) + (Number(selection.buldSlno) ? `-${Number(selection.buldSlno)}` : '');
  if (result.crs !== 'EPSG:4326' || structure.level4L !== selection.rn ||
      structure.level5 !== String(buildingNumber) || structure.level2 !== selection.sggNm)
    return { status: 'invalid', coordinate_provider: 'vworld' };
  const lng = Number(point.x), lat = Number(point.y);
  if (!Number.isFinite(lng) || !Number.isFinite(lat) || lng < 124 || lng > 132 || lat < 33 || lat > 39)
    return { status: 'invalid', coordinate_provider: 'vworld' };
  return { status: 'ready', lng, lat, coordinate_provider: 'vworld', source_crs: 'EPSG:4326',
    source_x: lng, source_y: lat, reason: 'juso_coordinate_key_pending' };
}

/** Only the Route Handler imports this module. Never logs keyed URLs/responses. */
export function createAddressProvider(keys: { juso?: string; vworld?: string },
  claim: (provider: 'juso_search' | 'vworld_coordinate') => Promise<void>,
  fetcher: typeof fetch = fetch): AddressProvider {
  async function request(endpoint: string, params: Record<string, string>, provider: 'juso_search' | 'vworld_coordinate') {
    await claim(provider);
    let httpStatus: number | null = null;
    let logged = false;
    const report = (stage: 'network' | 'response', code: unknown) => {
      // Only bounded machine codes: never provider text, URLs, keys or addresses.
      const safeCode = typeof code === 'string' && /^[A-Z][A-Z0-9_]{1,48}$/.test(code)
        && code !== keys.juso && code !== keys.vworld ? code : null;
      console.error('address_provider_failure', JSON.stringify({ provider, stage, http_status: httpStatus, code: safeCode }));
      logged = true;
    };
    try {
      const response = await fetcher(`${endpoint}?${new URLSearchParams(params)}`, {
        cache: 'no-store', signal: AbortSignal.timeout(10000), redirect: 'error',
      });
      httpStatus = response.status;
      const payload: unknown = await response.json();
      const data = payload as { response?: { status?: string; error?: { code?: unknown } };
        results?: { common?: { errorCode?: unknown } } } | null;
      const code = provider === 'vworld_coordinate' ? data?.response?.error?.code : data?.results?.common?.errorCode;
      const rejected = provider === 'vworld_coordinate'
        ? data?.response?.status === 'ERROR' : code !== undefined && code !== '0';
      if (!response.ok || rejected) report('response', code);
      if (!response.ok) throw new AddressError('address_provider_unavailable');
      return payload;
    } catch (error) {
      if (!logged) {
        const cause = error instanceof Error ? error.cause as { code?: unknown } | undefined : undefined;
        report(httpStatus === null ? 'network' : 'response',
          error instanceof Error && error.name === 'TimeoutError' ? 'TIMEOUT' : cause?.code);
      }
      throw new AddressError('address_provider_unavailable');
    }
  }
  const search: AddressProvider['search'] = async query => {
    if (!keys.juso) throw new AddressError('address_provider_not_configured', 503);
    return parseSearch(await request('https://business.juso.go.kr/addrlink/addrLinkApi.do', {
      confmKey: keys.juso, currentPage: '1', countPerPage: '100', keyword: query, resultType: 'json',
    }, 'juso_search'));
  };
  return { search, async locate(selection) {
    if (!keys.vworld) throw new AddressError('address_provider_not_configured', 503);
    // Re-fetch an exact road address: a client cannot supply a forged PNU/address.
    const matches = (await search(selection.roadAddrPart1)).choices.filter(c =>
      c.bdMgtSn === selection.bdMgtSn && c.pnu === selection.pnu && c.roadAddrPart1 === selection.roadAddrPart1);
    if (matches.length !== 1 || JSON.stringify(matches[0]) !== JSON.stringify(selection))
      throw new AddressError('address_selection_changed', 409);
    const verified = matches[0];
    return parseVworld(await request('https://api.vworld.kr/req/address', {
      service: 'address', request: 'getcoord', version: '2.0', crs: 'EPSG:4326',
      address: verified.roadAddrPart1, type: 'road', refine: 'true', simple: 'false', format: 'json', key: keys.vworld,
    }, 'vworld_coordinate'), verified);
  } };
}
