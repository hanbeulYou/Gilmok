import { afterEach, describe, expect, it, vi } from 'vitest';
import { createAddressProvider, parseSearch, parseSelection, parseJusoCoordinates } from '../../lib/geo/address-server';
const row = { admCd: '1168010600', rnMgtSn: '116803122008', udrtYn: '0', buldMnnm: '460', buldSlno: '0', mtYn: '0', lnbrMnnm: '912', lnbrSlno: '13', bdMgtSn: '1168010600109120013012822', roadAddrPart1: '서울특별시 강남구 역삼로 460', jibunAddr: '서울특별시 강남구 대치동 912-13', bdNm: '', rn: '역삼로', sggNm: '강남구', emdNm: '대치동' };
const search = { results: { common: { errorCode: '0', totalCount: '1' }, juso: [row] } };
const coords = { results: { common: { errorCode: '0', totalCount: '1' }, juso: [{ bdMgtSn: row.bdMgtSn, entX: '960800', entY: '1944000' }] } };
const project = vi.fn(async () => ({ lng: 127.0575, lat: 37.5025 }));
const keys = { juso: 'test-juso', jusoCoordinate: 'test-coordinate' };
describe('registration provider contract', () => {
  afterEach(() => { vi.restoreAllMocks(); project.mockClear(); });
  it('uses parcel numbers and preserves search choices', () => {
    expect(parseSelection(row).pnu).toBe('1168010600109120013');
    expect(parseSelection({ ...row, mtYn: '1' }).pnu).toBe('1168010600209120013');
    expect(parseSearch({ results: { common: { errorCode: '0', totalCount: '2' }, juso: [row, row] } }).choices).toHaveLength(2);
    expect(parseSearch({ results: { common: { errorCode: '0', totalCount: '0' } } }).choices).toEqual([]);
  });
  it('keeps source 5179 and projects only a matching unique building', async () => {
    const result = await parseJusoCoordinates(coords, parseSelection(row), project);
    expect(result).toMatchObject({ status: 'ready', coordinate_provider: 'juso', source_crs: 'EPSG:5179', source_x: 960800, source_y: 1944000, lng: 127.0575, lat: 37.5025, reason: null });
    expect(project).toHaveBeenCalledWith(960800,1944000);
    project.mockClear();
    const bad = structuredClone(coords); bad.results.juso[0].bdMgtSn = 'other';
    expect((await parseJusoCoordinates(bad, parseSelection(row), project)).status).toBe('invalid');
    bad.results.juso = [coords.results.juso[0], coords.results.juso[0]];
    expect((await parseJusoCoordinates(bad, parseSelection(row), project)).status).toBe('invalid');
    expect(project).not.toHaveBeenCalled();
  });
  it('does not project missing/invalid points or accept an invalid projection', async () => {
    const missing = { results: { common: { errorCode: '0', totalCount: '0' }, juso: [] } };
    expect((await parseJusoCoordinates(missing,parseSelection(row),project)).status).toBe('not_found');
    for (const x of ['', 'NaN', 'Infinity', '-1', '3000000']) {
      const bad = structuredClone(coords); bad.results.juso[0].entX = x;
      expect((await parseJusoCoordinates(bad,parseSelection(row),project)).status).toBe('invalid');
    }
    expect(project).not.toHaveBeenCalled();
    await expect(parseJusoCoordinates(coords,parseSelection(row),async()=>({lng:0,lat:0}))).rejects.toThrow('coordinate_projection_invalid');
  });
  it('reserves search/coordinate separately and never requests Vworld', async () => {
    const claim = vi.fn(async () => {});
    const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json(search)).mockResolvedValueOnce(Response.json(coords));
    const provider = createAddressProvider(keys,claim,project,fetcher);
    expect((await provider.locate(parseSelection(row))).status).toBe('ready');
    expect(claim.mock.calls).toEqual([['juso_search'],['juso_coordinate']]);
    const urls = fetcher.mock.calls.map(([u])=>new URL(String(u)));
    expect(urls.map(u=>u.hostname)).toEqual(['business.juso.go.kr','business.juso.go.kr']);
    expect(urls[1].pathname).toBe('/addrlink/addrCoordApi.do');
    for (const key of ['admCd','rnMgtSn','udrtYn','buldMnnm','buldSlno'] as const) expect(urls[1].searchParams.get(key)).toBe(row[key]);
    expect(urls[1].searchParams.get('confmKey')).toBe(keys.jusoCoordinate);
    for (const [,options] of fetcher.mock.calls) expect(options?.cache).toBe('no-store');
  });
  it('rejects forged selections before coordinate IO', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(search));
    const provider = createAddressProvider(keys,async()=>{},project,fetcher);
    await expect(provider.locate(parseSelection({...row,lnbrSlno:'14'}))).rejects.toThrow('address_selection_changed');
    expect(fetcher).toHaveBeenCalledTimes(1); expect(project).not.toHaveBeenCalled();
  });
  it('does not fall back when the coordinate key is missing or quota fails', async () => {
    const fetcher = vi.fn<typeof fetch>(), claim=vi.fn(async()=>{});
    await expect(createAddressProvider({juso:keys.juso},claim,project,fetcher).locate(parseSelection(row))).rejects.toThrow('address_provider_not_configured');
    expect(claim).not.toHaveBeenCalled();
    await expect(createAddressProvider(keys,async()=>{throw new Error('limit');},project,fetcher).search('역삼로 460')).rejects.toThrow('limit');
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('sanitizes transport and API errors, preserves operational error classification', async () => {
    const log=vi.spyOn(console,'error').mockImplementation(()=>{});
    const fetcher=vi.fn<typeof fetch>().mockRejectedValue(new Error('https://provider/?key=secret'));
    const provider=createAddressProvider(keys,async()=>{},project,fetcher);
    await expect(provider.search('역삼로 460')).rejects.toThrow(/^address_provider_unavailable$/);
    fetcher.mockResolvedValue(Response.json({results:{common:{errorCode:'E0001',errorMessage:'secret'}}}));
    await expect(provider.search('역삼로 460')).rejects.toThrow('juso_search_rejected');
    expect(JSON.stringify(log.mock.calls)).toContain('E0001');
    expect(JSON.stringify(log.mock.calls)).not.toContain('secret');
    expect(JSON.stringify(log.mock.calls)).not.toContain('역삼로');
    await expect(parseJusoCoordinates({results:{common:{errorCode:'E0001'}}},parseSelection(row),project)).rejects.toThrow('juso_coordinate_rejected');
  });
});
