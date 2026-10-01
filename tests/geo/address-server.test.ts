import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAddressProvider, parseSearch, parseSelection, parseVworld } from '../../lib/geo/address-server';
const row = { admCd: '1168010600', rnMgtSn: '116803122008', udrtYn: '0', buldMnnm: '460', buldSlno: '0',
  mtYn: '0', lnbrMnnm: '912', lnbrSlno: '13', bdMgtSn: '1168010600109120013012822',
  roadAddrPart1: '서울특별시 강남구 역삼로 460', jibunAddr: '서울특별시 강남구 대치동 912-13',
  bdNm: '', rn: '역삼로', sggNm: '강남구', emdNm: '대치동' };
const search = { results: { common: { errorCode: '0', totalCount: '1' }, juso: [row] } };
const coords = { response: { status: 'OK', result: { crs: 'EPSG:4326', point: { x: '127.05758573871447', y: '37.5025721944737' } },
  refined: { structure: { level4L: '역삼로', level5: '460', level2: '강남구' } } } };
describe('registration provider contract', () => {
  afterEach(() => vi.restoreAllMocks());
  it('uses legal land numbers, handles mountain separately, preserves multiple choices', () => {
    expect(parseSelection(row).pnu).toBe('1168010600109120013');
    expect(parseSelection({ ...row, mtYn: '1' }).pnu).toBe('1168010600209120013');
    expect(parseSearch({ results: { common: { errorCode: '0', totalCount: '2' }, juso: [row, row] } }).choices).toHaveLength(2);
    expect(parseSearch({ results: { common: { errorCode: '0', totalCount: '0' } } }).choices).toEqual([]);
    expect(() => parseSearch({ results: { common: { errorCode: 'E0001' } } })).toThrow('juso_search_rejected');
  });
  it('accepts exact A0 coordinate and refuses corrected address or unknown CRS', () => {
    expect(parseVworld(coords, parseSelection(row))).toMatchObject({ status: 'ready', lat: 37.5025721944737, lng: 127.05758573871447 });
    expect(parseVworld(coords, parseSelection({ ...row, buldMnnm: '461' })).status).toBe('invalid');
    const bad = structuredClone(coords); bad.response.result.crs = 'EPSG:5179';
    expect(parseVworld(bad, parseSelection(row)).status).toBe('invalid');
  });
  it('revalidates selection before one coordinate call, reserves each call, and never caches', async () => {
    const claim = vi.fn(async () => {});
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(search)).mockResolvedValueOnce(Response.json(coords));
    const provider = createAddressProvider({ juso: 'test-juso', vworld: 'test-vworld' }, claim, fetcher);
    expect((await provider.locate(parseSelection(row))).status).toBe('ready');
    expect(claim.mock.calls).toEqual([['juso_search'], ['vworld_coordinate']]);
    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const [, options] of fetcher.mock.calls) expect(options.cache).toBe('no-store');
  });
  it('rejects tampered selection before Vworld and does not retry provider errors', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const fetcher = vi.fn().mockResolvedValue(Response.json(search));
    const provider = createAddressProvider({ juso: 'secret', vworld: 'secret' }, async () => {}, fetcher);
    await expect(provider.locate(parseSelection({ ...row, bdNm: 'forged' }))).rejects.toThrow('address_selection_changed');
    expect(fetcher).toHaveBeenCalledTimes(1);
    fetcher.mockRejectedValue(new Error('https://provider/?key=secret'));
    await expect(provider.search('역삼로 460')).rejects.toThrow(/^address_provider_unavailable$/);
  });
  it('records only Vworld machine error codes when a coordinate response is rejected', async () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(search)).mockResolvedValueOnce(Response.json({
      response: { status: 'ERROR', error: { code: 'INVALID_KEY', text: 'secret-key private-address' } },
    }));
    const provider = createAddressProvider({ juso: 'test-juso', vworld: 'secret-key' }, async () => {}, fetcher);
    await expect(provider.locate(parseSelection(row))).rejects.toThrow('vworld_coordinate_rejected');
    expect(log.mock.calls).toEqual([['address_provider_failure', JSON.stringify({
      provider: 'vworld_coordinate', stage: 'response', http_status: 200, code: 'INVALID_KEY',
    })]]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it.each([
    [new TypeError('https://provider/?key=secret', { cause: { code: 'CERT_HAS_EXPIRED' } }), 'CERT_HAS_EXPIRED'],
    [new TypeError('private-address', { cause: { code: 'https://provider/?key=secret' } }), null],
    [new TypeError('private-address', { cause: { code: 'TEST_SECRET' } }), null],
  ])('sanitizes network failures without retrying or exposing credentials', async (error, code) => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    const fetcher = vi.fn().mockRejectedValue(error);
    const provider = createAddressProvider({ juso: 'TEST_SECRET' }, async () => {}, fetcher);
    await expect(provider.search('역삼로 460')).rejects.toThrow(/^address_provider_unavailable$/);
    expect(log.mock.calls).toEqual([['address_provider_failure', JSON.stringify({
      provider: 'juso_search', stage: 'network', http_status: null, code,
    })]]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('records a non-JSON upstream HTTP failure without its response body', async () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    const fetcher = vi.fn().mockResolvedValue(new Response('secret provider body', { status: 403 }));
    const provider = createAddressProvider({ juso: 'secret' }, async () => {}, fetcher);
    await expect(provider.search('역삼로 460')).rejects.toThrow(/^address_provider_unavailable$/);
    expect(log.mock.calls).toEqual([['address_provider_failure', JSON.stringify({
      provider: 'juso_search', stage: 'response', http_status: 403, code: null,
    })]]);
  });
  it('quota failure prevents all provider IO', async () => {
    const fetcher = vi.fn();
    const provider = createAddressProvider({ juso: 'key' }, async () => { throw new Error('daily_limit_reached'); }, fetcher);
    await expect(provider.search('역삼로 460')).rejects.toThrow('daily_limit_reached');
    expect(fetcher).not.toHaveBeenCalled();
  });
});
