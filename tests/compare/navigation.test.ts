import { beforeEach, expect, it, vi } from 'vitest';
import { navigationIndex } from '../../lib/compare/navigation';
import { useComparisonStore, type NewCandidate } from '../../lib/compare/store';
import { candidate, context } from '../scoring/fixtures';
vi.mock('../../lib/supabase/session', () => ({ ensureSession: vi.fn(() => new Promise(() => {})) }));
const value = { alias: '후보', candidate, selection: {}, location: {}, resolved: { context } } as NewCandidate;
beforeEach(() => useComparisonStore.getState().clear());
it('wraps directional navigation and supports endpoints without intercepting other keys', () => {
  expect(navigationIndex('ArrowRight', 2, 3)).toBe(0);
  expect(navigationIndex('ArrowLeft', 0, 3)).toBe(2);
  expect(navigationIndex('ArrowDown', 0, 3)).toBe(1);
  expect(navigationIndex('ArrowUp', 1, 3)).toBe(0);
  expect(navigationIndex('Home', 2, 3)).toBe(0);
  expect(navigationIndex('End', 0, 3)).toBe(2);
  expect(navigationIndex('Tab', 0, 3)).toBeNull();
  expect(navigationIndex('ArrowRight', 0, 0)).toBeNull();
});
it('selects without opening evidence, keeps open evidence synchronized, and preserves manual order', () => {
  const s = useComparisonStore.getState(), a = s.add(value), b = s.add(value);
  s.move(b, a); s.selectCandidate(a);
  expect(useComparisonStore.getState()).toMatchObject({ selectedId: a, evidenceOpen: false, order: [b, a] });
  s.openEvidence(a, 'building'); s.selectCandidate(b);
  expect(useComparisonStore.getState()).toMatchObject({ selectedId: b, selectedAxis: null, evidenceOpen: true, order: [b, a] });
  s.closeEvidence();
  expect(useComparisonStore.getState().selectedId).toBe(b);
});
it('keeps selection on floor edits and falls back to the first displayed survivor on removal', () => {
  const s = useComparisonStore.getState(), a = s.add(value), b = s.add(value), c = s.add(value);
  s.move(c, a); s.selectCandidate(b); s.edit(b, '다른 층', 4);
  expect(useComparisonStore.getState().selectedId).toBe(b);
  s.remove(b);
  expect(useComparisonStore.getState()).toMatchObject({ selectedId: c, order: [c, a] });
  s.remove(c); s.remove(a);
  expect(useComparisonStore.getState()).toMatchObject({ selectedId: null, candidates: [], order: [], evidenceOpen: false });
});
