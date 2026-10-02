import { expect, it, vi } from 'vitest';
import { scoreCandidate, useComparisonStore, type NewCandidate } from '../../lib/compare/store';
import { loadCandidate } from '../../lib/compare/load-candidate';
import { score } from '../../lib/scoring/score';
import { academyV0 } from '../../lib/scoring/presets';
import { candidate, context, inputs, reference } from '../scoring/fixtures';

vi.mock('../../lib/supabase/client', () => ({ getSupabaseClient: () => ({}) }));
vi.mock('../../lib/supabase/session', () => ({ ensureSession: async () => ({}) }));
vi.mock('../../lib/compare/load-candidate', () => ({ loadCandidate: vi.fn() }));

it('runs at most two of five candidate jobs, releasing a slot after success or failure', async () => {
  const store = useComparisonStore.getState();
  const result = score(inputs(), inputs(1000), [], null, candidate, academyV0, reference(), context);
  const started: number[] = [];
  const gates = new Map<number, { resolve: () => void; reject: (error: Error) => void }>();
  let running = 0, maximum = 0, draining = false;
  vi.mocked(loadCandidate).mockImplementation(async (_client, candidate) => {
    started.push(candidate.floor);
    maximum = Math.max(maximum, ++running);
    try {
      if (!draining) await new Promise<void>((resolve, reject) => {
        gates.set(candidate.floor, { resolve, reject });
      });
      return { result, inputs: { key: 'concurrency-fixture' }, lookupRequestId: null,
        lookupStatus: 'ready', stage: 'scored', error: undefined };
    } finally { running--; }
  });
  const ids = [1, 2, 3, 4, 5].map(floor => store.add({ alias: `후보 ${floor}`,
    candidate: { ...candidate, floor }, selection: {}, location: {},
    resolved: { status: 'footprint_missing', context, building: null },
  } as NewCandidate));
  const jobs = ids.map(id => scoreCandidate(id));
  try {
    await vi.waitFor(() => expect(started).toEqual([1, 2]));
    expect(running).toBe(2);
    gates.get(1)!.resolve();
    await jobs[0];
    await vi.waitFor(() => expect(started).toEqual([1, 2, 3]));
    expect(running).toBe(2);

    gates.get(2)!.reject(new Error('controlled candidate failure'));
    await jobs[1];
    await vi.waitFor(() => expect(started).toEqual([1, 2, 3, 4]));
    expect(useComparisonStore.getState().candidates.find(c => c.id === ids[1])?.stage).toBe('error');
    expect(running).toBe(2);

    gates.get(3)!.resolve();
    await jobs[2];
    await vi.waitFor(() => expect(started).toEqual([1, 2, 3, 4, 5]));
    expect(running).toBe(2);
    gates.get(4)!.resolve(); gates.get(5)!.resolve();
    await Promise.all(jobs);
    expect(maximum).toBe(2);
    expect(running).toBe(0);
    expect(useComparisonStore.getState().candidates.filter(c => c.stage === 'scored')).toHaveLength(4);
  } finally {
    draining = true;
    for (const gate of gates.values()) gate.resolve();
    await Promise.all(jobs);
    for (const id of ids) store.remove(id);
  }
});
