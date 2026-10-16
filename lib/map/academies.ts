import type { FeatureCollection, Point } from 'geojson';

export interface AcademyLayerRequest {
  lat: number; lng: number; radius_m: 800 | 1000; field: string;
  expected_source: Readonly<Record<string, unknown>>;
  expected_same_field_count: number;
}
export interface AcademyPoint {
  name: string; field: string;
  floor_label: string | null;
  floor_status: 'explicit' | 'missing' | 'ambiguous';
  coordinate_verification_pending: boolean;
  coordinate_review_reason: 'movement_gt_500m' | null;
  coordinate_review_version: string | null;
}
export interface AcademyCounts {
  radius_all: number; radius_same_field: number;
  radius_pending: number; radius_same_field_pending: number;
  by_field: Record<string, number>;
}
interface Envelope {
  schema_version: '1.0'; center: [number, number]; radius_m: 800 | 1000; field: string;
}
export interface ReadyAcademyLayer extends Envelope {
  status: 'ready'; reason: null;
  collection: FeatureCollection<Point, AcademyPoint>;
  counts: AcademyCounts;
  meta: {
    crs: 'EPSG:4326'; source: Record<string, unknown>;
    source_revision: string; coordinate_provider: 'juso'; review_version: string;
    unlocated_count_seoul: number;
    quality_inventory: { academy: number; school: number };
  };
}
export interface UnavailableAcademyLayer extends Envelope {
  status: 'outside_coverage' | 'coordinate_replacement_pending' | 'source_mismatch';
  reason: string; collection: null; counts: null; meta: null;
}
export interface DenseAcademyLayer extends Envelope {
  status: 'too_dense'; reason: 'response_budget_exceeded'; collection: null; counts: null;
  meta: { radius_count: number; jsonb_bytes: number; raw_budget_bytes: number };
}
export type AcademyLayer = ReadyAcademyLayer | UnavailableAcademyLayer | DenseAcademyLayer;

function requireValue(condition: unknown): asserts condition {
  if (!condition) throw new Error('학원 데이터 기준이 달라 재계산이 필요합니다.');
}
function object(value: unknown): Record<string, unknown> {
  requireValue(value !== null && typeof value === 'object' && !Array.isArray(value));
  return value as Record<string, unknown>;
}
function integer(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) >= 0; }
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') return `{${Object.entries(value)
    .sort(([a], [b]) => a.localeCompare(b)).map(([k,v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`;
  return JSON.stringify(value) ?? 'undefined';
}

/** Caller supplies the exact scoring center, source metadata and cluster n_field. No candidate/uid/address. */
export function academyLayerArgs(request: AcademyLayerRequest) {
  requireValue(Number.isFinite(request.lat) && request.lat >= 33 && request.lat <= 39 &&
    Number.isFinite(request.lng) && request.lng >= 124 && request.lng <= 132 &&
    [800,1000].includes(request.radius_m) && typeof request.field === 'string' &&
    [...request.field].length <= 200 && integer(request.expected_same_field_count) &&
    object(request.expected_source).available === true);
  return { lat: request.lat, lng: request.lng, radius_m: request.radius_m,
    requested_field: request.field, expected_source: request.expected_source };
}

/** Validate the full radius set before B renders any points; missing/stale never masquerades as zero. */
export function parseAcademyLayer(input: unknown, request: AcademyLayerRequest): AcademyLayer {
  academyLayerArgs(request);
  const value = object(input);
  requireValue(value.schema_version === '1.0' && Array.isArray(value.center) && value.center.length === 2 &&
    value.center[0] === request.lng && value.center[1] === request.lat &&
    value.radius_m === request.radius_m && value.field === request.field);
  if (value.status !== 'ready') {
    requireValue(value.collection === null && value.counts === null && typeof value.reason === 'string');
    if (value.status === 'too_dense') {
      const meta = object(value.meta);
      requireValue(value.reason === 'response_budget_exceeded' && integer(meta.radius_count) &&
        integer(meta.jsonb_bytes) && integer(meta.raw_budget_bytes));
    } else requireValue(['outside_coverage','coordinate_replacement_pending','source_mismatch']
      .includes(value.status as string) && value.meta === null);
    return value as unknown as AcademyLayer;
  }
  const meta = object(value.meta), counts = object(value.counts), collection = object(value.collection);
  requireValue(value.reason === null && meta.crs === 'EPSG:4326' && meta.coordinate_provider === 'juso' &&
    typeof meta.source_revision === 'string' && meta.source_revision.length > 0 &&
    typeof meta.review_version === 'string' && meta.review_version.length > 0 &&
    canonical(meta.source) === canonical(request.expected_source) && integer(meta.unlocated_count_seoul));
  const inventory = object(meta.quality_inventory);
  requireValue(integer(inventory.academy) && integer(inventory.school));
  for (const key of ['radius_all','radius_same_field','radius_pending','radius_same_field_pending']) requireValue(integer(counts[key]));
  requireValue(collection.type === 'FeatureCollection' && Array.isArray(collection.features));
  const ids = new Set<string>(), fields = new Map<string,number>();
  let same = 0, pending = 0, samePending = 0;
  for (const item of collection.features) {
    const feature = object(item), geometry = object(feature.geometry), p = object(feature.properties);
    requireValue(feature.type === 'Feature' && typeof feature.id === 'string' && feature.id.length > 0 && !ids.has(feature.id));
    ids.add(feature.id);
    requireValue(geometry.type === 'Point' && Array.isArray(geometry.coordinates) && geometry.coordinates.length === 2 &&
      typeof geometry.coordinates[0] === 'number' && geometry.coordinates[0] >= 124 && geometry.coordinates[0] <= 132 &&
      typeof geometry.coordinates[1] === 'number' && geometry.coordinates[1] >= 33 && geometry.coordinates[1] <= 39);
    const allowed = ['name','field','floor_label','floor_status','coordinate_verification_pending',
      'coordinate_review_reason','coordinate_review_version'];
    requireValue(Object.keys(p).length === allowed.length && Object.keys(p).every(k => allowed.includes(k)) &&
      typeof p.name === 'string' && typeof p.field === 'string' &&
      ['explicit','missing','ambiguous'].includes(p.floor_status as string));
    requireValue(p.floor_status === 'explicit' ? typeof p.floor_label === 'string' && p.floor_label.length > 0 : p.floor_label === null);
    requireValue(typeof p.coordinate_verification_pending === 'boolean');
    requireValue(p.coordinate_verification_pending ? p.coordinate_review_reason === 'movement_gt_500m' &&
      p.coordinate_review_version === meta.review_version : p.coordinate_review_reason === null && p.coordinate_review_version === null);
    fields.set(p.field, (fields.get(p.field) ?? 0) + 1);
    if (p.field === request.field) same++;
    if (p.coordinate_verification_pending) { pending++; if (p.field === request.field) samePending++; }
  }
  const byField = object(counts.by_field);
  requireValue(Object.entries(byField).every(([k,n]) => integer(n) && n === fields.get(k)) &&
    Object.keys(byField).length === fields.size && ids.size === counts.radius_all &&
    same === counts.radius_same_field && same === request.expected_same_field_count &&
    pending === counts.radius_pending && samePending === counts.radius_same_field_pending);
  return value as unknown as ReadyAcademyLayer;
}

/** B passes rendered source IDs. Tile copies and coincident institutions count by distinct institution ID. */
export function academyViewportCounts(value: ReadyAcademyLayer, visibleIds: readonly string[]) {
  const visible = new Set(visibleIds);
  const features = value.collection.features.filter(f => visible.has(String(f.id)));
  return { radiusSameFieldN: value.counts.radius_same_field,
    viewportSameFieldM: features.filter(f => f.properties.field === value.field).length,
    viewportAll: features.length,
    radiusSameFieldPending: value.counts.radius_same_field_pending,
    viewportSameFieldPending: features.filter(f => f.properties.field === value.field && f.properties.coordinate_verification_pending).length };
}

/** One in flight, latest generation wins. B owns the 250ms selection debounce and zoom>=15 gate. */
export function createAcademyLayerLoader(fetcher: (args: ReturnType<typeof academyLayerArgs>, signal: AbortSignal) => Promise<unknown>) {
  const cache = new Map<string, ReadyAcademyLayer>();
  let generation = 0, controller: AbortController | undefined, queue: Promise<unknown> = Promise.resolve();
  const aborted = () => new DOMException('Selection changed', 'AbortError');
  return {
    load(request: AcademyLayerRequest): Promise<AcademyLayer> {
      const args = academyLayerArgs(request), key = canonical(request), mine = ++generation;
      controller?.abort();
      const cached = cache.get(key);
      if (cached) { cache.delete(key); cache.set(key,cached); return Promise.resolve(cached); }
      const job = queue.catch(() => undefined).then(async () => {
        if (mine !== generation) throw aborted();
        const active = new AbortController(); controller = active;
        const timer = setTimeout(() => active.abort(), 15000);
        try {
          const result = await fetcher(args, active.signal);
          if (mine !== generation || active.signal.aborted) throw aborted();
          const value = parseAcademyLayer(result, request);
          if (value.status === 'ready') {
            cache.set(key,value);
            if (cache.size > 5) cache.delete(cache.keys().next().value!);
          }
          return value;
        } finally { clearTimeout(timer); if (controller === active) controller = undefined; }
      });
      queue = job; return job;
    },
    dispose() { generation++; controller?.abort(); cache.clear(); },
  };
}
