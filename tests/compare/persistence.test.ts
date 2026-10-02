import { describe, expect, it } from 'vitest';
import { deserializeCandidate, normalizedWeights, serializeCandidate, validWeights } from '../../lib/compare/persistence';
import { academyV0 } from '../../lib/scoring/presets';
import type { ComparisonCandidate } from '../../lib/compare/store';

describe('owner persistence contract', () => {
  it('preserves raw sliders instead of restoring normalized percentages', () => {
    const raw = { ...academyV0.weights, demand:17 };
    expect(normalizedWeights(raw).demand).toBeCloseTo(17/87,14);
    expect(validWeights(raw)).toBe(true);
    expect(validWeights({ ...raw, demand:41 })).toBe(false);
    expect(validWeights({ ...raw, extra:1 })).toBe(false);
    expect(validWeights({ ...raw, demand:NaN })).toBe(false);
  });
  it('round-trips private rent NULL versus zero, pending identity and address provenance', () => {
    const row = { id:'owner-candidate', alias:'검증', candidate:{ lat:37.5,lng:127.05,floor:3,address:'공개 주소',
      deposit_krw:0,monthly_rent_krw:null,maintenance_krw:0,exclusive_area_m2:42 },
      selection:{ pnu:'1168010600109120013' }, location:{ status:'ready' }, resolved:{ status:'footprint_missing' },
      lookupRequestId:'owner-request',lookupStatus:'pending' } as ComparisonCandidate;
    const restored = deserializeCandidate(serializeCandidate(row));
    expect(restored.candidate).toEqual(row.candidate);
    expect(restored.lookupRequestId).toBe(row.lookupRequestId);
    expect(restored.lookupStatus).toBe('pending');
    expect(restored.selection).toEqual(row.selection);
    expect(restored.result).toBeUndefined(); // Reopen gets fresh RPC/Worker; snapshots never become new inputs.
  });
});
