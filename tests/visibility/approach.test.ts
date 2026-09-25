import { expect, it } from 'vitest';
import { computeVisibility } from '../../lib/visibility/compute.ts';
import { approachEvidence } from '../../lib/visibility/approach.ts';
import { building, rectangle, scene } from './fixtures.ts';

it('walks from each anchor toward the candidate and reports distance, never adding approach scores', () => {
  const s = scene(); s.buildings = [building('wall', rectangle(50, -1, 60, 1), 100)];
  const baseline = computeVisibility(s);
  s.stations = [{ id: 'east', name: '역', point: [200, 0], distance_m: 200 }];
  s.schools = [{ id: 'school', name: '학교', point: [200, 0], distance_m: 200 }];
  const result = computeVisibility(s);
  expect(result.status === 'ready' && result.visible_ratio).toBe(baseline.status === 'ready' && baseline.visible_ratio);
  const routes = approachEvidence(s, result.samples);
  // 10/20/30/40m from candidate are visible; >=50m is behind the wall. First exposure at 40m.
  expect(routes).toMatchObject([
    { anchor_id: 'east', first_exposure_distance_m: 160, sample_id: 'station:east:4', sampling_interval_m: 10, estimated: true },
    { anchor_id: 'school', first_exposure_distance_m: 160, sample_id: 'school:school:2', sampling_interval_m: 20 },
  ]);
  expect(result.summary.all.total_weight).toBe(result.summary.ring.total_weight);
  expect(result.summary.station.total_weight).toBe(0);
  s.sources = { ...s.sources, subway_positions: { available: false }, schools: { available: false } };
  const missing = computeVisibility(s);
  expect(missing.status === 'ready' && missing.visible_ratio).toBe(baseline.status === 'ready' && baseline.visible_ratio);
  expect(approachEvidence(s, missing.samples)).toMatchObject([
    { first_exposure_distance_m: null, reason: 'source_unavailable' },
    { first_exposure_distance_m: null, reason: 'source_unavailable' },
  ]);
});

it('reports zero at a visible departure point and NULL when no approach sample is visible', () => {
  const s = scene(); s.stations = [{ id: 'east', name: '역', point: [200, 0], distance_m: 200 }];
  expect(approachEvidence(s, computeVisibility(s).samples)[0].first_exposure_distance_m).toBe(0);
  s.buildings = [building('wall', rectangle(1, -5, 2, 5), 100)];
  expect(approachEvidence(s, computeVisibility(s).samples)[0]).toMatchObject({
    first_exposure_distance_m: null, reason: 'no_visible_sample_on_approach',
  });
});

it('ignores samples pushed beyond the departure point, using moved positions within the approach', () => {
  const s = scene(); s.candidate_building_id = 'self'; s.containing_building_count = 1;
  s.buildings = [building('self', rectangle(-1, -1, 49, 1), 100)];
  s.stations = [{ id: 'east', name: '역', point: [50, 0], distance_m: 50 }];
  const r = computeVisibility(s), moved = r.samples.filter(p => p.group === 'station' && p.moved_m > 0);
  // Candidate prism is ignored for rays; indoor samples are pushed to x=49.001.
  expect(approachEvidence(s, moved)[0].first_exposure_distance_m).toBeCloseTo(.999, 6);
  s.stations = [{ ...s.stations[0], point: [48, 0], distance_m: 48 }];
  expect(approachEvidence(s, computeVisibility(s).samples)[0].first_exposure_distance_m).toBeNull();
});

it('cannot rescue an invalid ring score with visible approaches', () => {
  const s = scene(); s.candidate_building_id = 'self'; s.containing_building_count = 1;
  s.buildings = [building('self', rectangle(-100, -100, 100, 100), 100)];
  s.stations = [{ id: 'east', name: '역', point: [500, 0], distance_m: 500 }];
  const result = computeVisibility(s);
  expect(result.summary.station.visible).toBeGreaterThan(0);
  expect(result).toMatchObject({ status: 'missing', reason: 'no_valid_ring_samples' });
});
