import { readFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { score, reweight } from '../../lib/scoring/score.ts';
import { exposureAxis } from '../../lib/scoring/axes.ts';
import { academyV0 } from '../../lib/scoring/presets.ts';
import type { Candidate, ExposureInput, ScoreInputs, ScoreContext, ScoringReference, ScoreResult } from '../../lib/scoring/types.ts';
import { candidate, inputs, reference, context } from './fixtures.ts';

interface Case { key: string; candidate: Candidate; primary: ScoreInputs; school: ScoreInputs; context: ScoreContext;
  reference: ScoringReference; exposure: ExposureInput; baseline: ScoreResult }
const { cases } = JSON.parse(gunzipSync(readFileSync(new URL('./fixtures/v040-inputs.json.gz', import.meta.url))).toString()) as { cases: Case[] };
const run = (c: Case) => score(c.primary, c.school, [], c.exposure, c.candidate, academyV0, c.reference, c.context);
const expected = { a: 83.10201719669011, b: 92.60289331263688, c: 82.67204741731668, d: 81.84736541572254, e: 85.08500496915157 };

describe('v0.4.0 recorded public candidates', () => {
  it.each(cases)('$key preserves all other axes, confidence and missingness', c => {
    const result = run(c);
    expect(result.preset.version).toBe('0.4.0');
    expect(result.confidence).toEqual(c.baseline.confidence);
    for (const axis of result.axes) if (!['building', 'exposure'].includes(axis.key))
      expect(axis).toEqual(c.baseline.axes.find(a => a.key === axis.key));
    expect(result.axes.filter(a => a.normalized === null).map(a => a.key))
      .toEqual(c.baseline.axes.filter(a => a.normalized === null).map(a => a.key));
    if (c.key.startsWith('random-')) {
      expect(result.axes.find(a => a.key === 'building')?.normalized).toBeNull();
      expect(result.axes.find(a => a.key === 'exposure')?.normalized).toBeNull();
      expect(result.total).toBe(c.baseline.total);
    } else expect(result.total).toBeCloseTo(expected[c.key as keyof typeof expected], 10);
  });
  it('meets e−a≥1.5, a>d and the approved five-candidate order', () => {
    const values = Object.fromEntries(cases.slice(0, 5).map(c => [c.key, run(c).total!]));
    expect(values.e - values.a).toBeGreaterThanOrEqual(1.5);
    expect(values.a).toBeGreaterThan(values.d);
    expect(Object.keys(values).sort((a, b) => values[b] - values[a])).toEqual(['b', 'e', 'a', 'c', 'd']);
  });
  it('requires re-scoring a v0.3 result before slider reweighting', () => {
    expect(() => reweight(cases[0].baseline, academyV0.weights)).toThrow('model version mismatch');
  });
});

it.each([[1, 1], [2, .9], [3, .8], [4, .7], [6, .7], [-1, .8], [-3, .8]])('Y coefficient at floor %s is %s and preserves geometry', (floor, factor) => {
  const exposure = { status: 'ready', model_version: '0.2.2', visible_ratio: .4 } as const;
  const axis = exposureAxis(exposure, { ...candidate, floor });
  expect(exposure.visible_ratio).toBe(.4);
  expect(axis.raw).toBeCloseTo(.4 * factor);
  expect(axis.normalized).toBeCloseTo(40 * factor);
  expect(axis.evidence.values).toMatchObject({ requested_floor: floor, visible_ratio: .4, floor_attention_coefficient: factor });
  expect(axis.evidence.notes.some(n => n.includes('모델 가정'))).toBe(true);
  if (floor < 0) expect(axis.evidence.notes).toContain('지하: 입구 간판 기준 노출');
});
it.each(['pending', 'missing'] as const)('keeps exposure %s despite a known coefficient', status => {
  expect(exposureAxis({ status, reason: 'fixture' }, candidate)).toMatchObject({ status, raw: null, normalized: null });
});

describe('unknown passenger elevator policy', () => {
  const at = (floor: number, passenger: number | null, status = 'ready', unlinked = false) => {
    const p = inputs(), school = inputs(1000);
    p.meta.floor = school.meta.floor = floor;
    p.meta.building_lookup.status = status;
    p.building!.elevators = { passenger, emergency: 1 };
    if (unlinked) p.building!.register_pk = null;
    return score(p, school, [], { status: 'ready', model_version: '0.2.2', visible_ratio: .4 },
      { ...candidate, floor }, academyV0, reference(p), context);
  };
  it.each([[1, 10], [2, 5], [-1, -25], [-3, -25]])('floor %s applies shared row without penalty', (floor, adjustment) => {
    const result = at(floor, null), known = at(floor, 0);
    const b = result.axes.find(a => a.key === 'building')!;
    expect(b.raw).toBe(known.axes.find(a => a.key === 'building')!.raw);
    expect(b.evidence.values.floor_adjustment).toBe(adjustment);
    expect(b.evidence.notes).toContain('승강기 미확인(대장 값 없음)');
    expect(result.confidence).toEqual(known.confidence);
    if (floor < 0) {
      expect(b.evidence.rules_applied).toContain('R7:-25');
      expect(b.evidence.rules_applied.some(r => r.startsWith('R3_R4:'))).toBe(false);
    }
  });
  it.each([3, 4, 5, 6])('floor %s holds adjustment at zero and deducts five confidence points', floor => {
    const result = at(floor, null), known = at(floor, 0);
    const b = result.axes.find(a => a.key === 'building')!;
    expect(b.evidence.values.floor_adjustment).toBe(0);
    expect(b.raw).toBe(85);
    expect(result.confidence.value).toBe(known.confidence.value - 5);
    expect(result.confidence.reasons).toContain('승강기 미확인(대장 값 없음) (-5)');
  });
  it.each(['pending', 'processing'])('%s holds 60 and deducts only the existing 15', status => {
    const result = at(4, null, status), ready = at(4, 0);
    expect(result.axes.find(a => a.key === 'building')).toMatchObject({ raw: 60, status: 'pending' });
    expect(result.confidence.value).toBe(ready.confidence.value - 15);
    expect(result.confidence.reasons).not.toContain('승강기 미확인(대장 값 없음) (-5)');
  });
  it('preserves the independent unlinked-register deduction', () => {
    const result = at(3, null, 'ready', true), linked = at(3, null);
    expect(result.confidence.value).toBe(linked.confidence.value - 10);
    expect(result.confidence.reasons).toContain('건물 대장 미연결, 용도·승강기 미확인 (-10)');
  });
});
