import { at } from './geometry.ts';
import type { Anchor, VisibilitySample, VisibilityScene } from './types.ts';
export function generateSamples(scene: VisibilityScene): VisibilitySample[] {
  const samples: VisibilitySample[] = [];
  for (let bearing = 0; bearing < 360; bearing += 10) for (const radius of [20, 40, 60]) {
    const angle = bearing * Math.PI / 180;
    samples.push({ id: `ring:${bearing}:${radius}`, group: 'ring', bearing_deg: bearing, radius_m: radius,
      point: [scene.candidate[0] + Math.sin(angle) * radius, scene.candidate[1] + Math.cos(angle) * radius], weight: 100 / radius });
  }
  const path = (anchor: Anchor, group: 'station' | 'school', n: number) => {
    for (let i = 1; i <= n; i++) samples.push({ id: `${group}:${anchor.id}:${i}`, group, anchor_id: anchor.id,
      step: i, point: at(scene.candidate, anchor.point, i / n), weight: 0 });
  };
  if (scene.sources.subway_positions?.available) for (const station of scene.stations) path(station, 'station', 20);
  if (scene.sources.schools?.available) for (const school of scene.schools) path(school, 'school', 10);
  return samples;
}
