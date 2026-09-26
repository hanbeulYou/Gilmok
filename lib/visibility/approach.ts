import type { SampleResult, VisibilityScene } from './types.ts';

/** Evidence only: distance from the anchor to the first visible sampled point toward the candidate. */
export function approachEvidence(scene: VisibilityScene, samples: readonly SampleResult[]) {
  return (['station', 'school'] as const).flatMap(group => {
    const available = !!scene.sources[group === 'station' ? 'subway_positions' : 'schools']?.available;
    return (group === 'station' ? scene.stations : scene.schools).map(anchor => {
      const length = Math.hypot(anchor.point[0] - scene.candidate[0], anchor.point[1] - scene.candidate[1]);
      const visible = samples.filter(s => available && s.group === group && s.anchor_id === anchor.id && s.status === 'visible')
        .map(s => ({ sample: s, radius: Math.hypot(s.point[0] - scene.candidate[0], s.point[1] - scene.candidate[1]),
          distance: Math.hypot(s.point[0] - anchor.point[0], s.point[1] - anchor.point[1]) }))
        .filter(s => s.radius <= length + 1e-6) // An outward push beyond the departure point is not on the approach.
        .sort((a, b) => a.distance - b.distance || a.sample.id.localeCompare(b.sample.id));
      const first = visible[0];
      return { anchor_id: anchor.id, name: anchor.name, group, line: anchor.line ?? null, level: anchor.level ?? null,
        first_exposure_distance_m: first?.distance ?? null, sample_id: first?.sample.id ?? null,
        sampling_interval_m: length / (group === 'station' ? 20 : 10), estimated: true,
        reason: !available ? 'source_unavailable' : first ? null : 'no_visible_sample_on_approach' };
    });
  });
}
