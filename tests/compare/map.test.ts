import { describe, expect, it, vi } from 'vitest';
import { createMapContextLoader } from '../../lib/map/context';
import { contextSummary, groupCandidates, mapSourceFingerprint, type MapContext } from '../../lib/map/features';
import type { ComparisonCandidate } from '../../lib/compare/store';

const row = (id: string, floor: number, lng = 127.057585738094) => ({ id, alias: id,
  candidate: { floor, lat: 37.5025724504279, lng } } as ComparisonCandidate);
const value = (lat: number, lng: number) => ({ schema_version: '1.0', center: [lng, lat],
  collection: { type: 'FeatureCollection', features: [] }, meta: { covered: true, crs: 'EPSG:4326',
    sources: { schools: { available: true, unlocated_count: 7, sources: [], source_versions: [], latest_ingested_at: null },
      transit_stops: { available: true, unlocated_count: 0, sources: [], source_versions: [], latest_ingested_at: null } } } } as MapContext);

describe('map scoring coordinates and context', () => {
  it('groups only identical points, keeps all floors, IDs and matrix ranks without rounding', () => {
    const rows = [row('a',3),row('b',2,127.058),row('d',4),row('e',1)];
    const grouped = groupCandidates(rows);
    expect(grouped).toHaveLength(2);
    expect(grouped[0].coordinate).toEqual([rows[0].candidate.lng,rows[0].candidate.lat]);
    expect(grouped[0].members.map(x => [x.id,x.floor,x.rank])).toEqual([['a',3,1],['d',4,3],['e',1,4]]);
    expect(groupCandidates([row('a',3),row('b',3,127.0575857380941)])).toHaveLength(2);
    expect(mapSourceFingerprint(row('a',1))).toBe(mapSourceFingerprint(row('a',4)));
  });
  it('distinguishes zero counts, missing sources and Seoul coverage', () => {
    const data = value(37.5,127);
    expect(contextSummary(data)).toContain('역 0곳');
    expect(contextSummary(data)).toContain('원천 전체 학교 좌표 미상 7곳');
    data.meta.sources.schools.available = false;
    expect(contextSummary(data)).toContain('학교 자료를 불러오지 못함');
    data.meta.covered = false;
    expect(contextSummary(data)).toContain('서울 밖');
  });
  it('uses score_inputs subway_positions metadata, so a station refresh invalidates the map cache', () => {
    const sourceRow = (version: string) => ({ ...row('a',3), inputs: { primary: { meta: {
      sources: { subway_positions: { source_version: version }, schools: { source_version:'fixed' } },
    } } } } as unknown as ComparisonCandidate);
    expect(mapSourceFingerprint(sourceRow('2026-09'))).not.toBe(mapSourceFingerprint(sourceRow('2026-10')));
  });
  it('shares work, skips queued stale selections, serializes network and invalidates source versions', async () => {
    let release!: () => void;
    const first = new Promise<void>(resolve => { release = resolve; });
    let active = 0, max = 0;
    const fetcher = vi.fn(async (lat: number, lng: number) => { active++; max = Math.max(max, active);
      if (lat === 37.5) await first; active--; return value(lat,lng); });
    const loader = createMapContextLoader(fetcher);
    const a = loader.load(37.5,127,'v1'); expect(loader.load(37.5,127,'v1')).toBe(a);
    await Promise.resolve(); await Promise.resolve();
    const b = loader.load(37.6,127,'v1').catch(error => error.name);
    const c = loader.load(37.7,127,'v1'); release();
    await a; expect(await b).toBe('AbortError'); await c;
    expect(fetcher).toHaveBeenCalledTimes(2); expect(max).toBe(1);
    await loader.load(37.7,127,'v1'); expect(fetcher).toHaveBeenCalledTimes(2);
    await loader.load(37.7,127,'v2'); expect(fetcher).toHaveBeenCalledTimes(3);
    loader.dispose();
  });
  it('does not cache a failed call or a center with swapped coordinates', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(value(127,37.5)).mockResolvedValue(value(37.5,127));
    const loader = createMapContextLoader(fetcher);
    await expect(loader.load(37.5,127,'v')).rejects.toThrow('offline');
    await expect(loader.load(37.5,127,'v')).rejects.toThrow('중심 좌표');
    await expect(loader.load(37.5,127,'v')).resolves.toHaveProperty('center',[127,37.5]);
  });
});
