import type { Footprint, Ring, XY } from './types.ts';
/** One micrometre in metric XY; numerical tolerance, not a building buffer. */
const EPS = 1e-6;
const cross = (a: XY, b: XY) => a[0] * b[1] - a[1] * b[0];
const sub = (a: XY, b: XY): XY => [a[0] - b[0], a[1] - b[1]];
const dot = (a: XY, b: XY) => a[0] * b[0] + a[1] * b[1];
export const at = (a: XY, b: XY, t: number): XY => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
function closest(a: XY, b: XY, p: XY): XY {
  const d = sub(b, a), n = dot(d, d);
  return at(a, b, n === 0 ? 0 : Math.max(0, Math.min(1, dot(sub(p, a), d) / n)));
}
function onEdge(p: XY, a: XY, b: XY): boolean {
  const q = closest(a, b, p);
  return Math.hypot(p[0] - q[0], p[1] - q[1]) <= EPS;
}
/** 0=outside, 1=inside, 2=boundary. Closed rings are validated at entry. */
function inRing(p: XY, ring: Ring): number {
  let inside = false;
  for (let i = 1; i < ring.length; i++) {
    const a = ring[i - 1], b = ring[i];
    if (onEdge(p, a, b)) return 2;
    if ((a[1] > p[1]) !== (b[1] > p[1]) &&
      p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside ? 1 : 0;
}
export function covers(polygons: Footprint, p: XY): boolean {
  return polygons.some(([outer, ...holes]) => {
    const outerState = inRing(p, outer);
    if (outerState === 2) return true;
    if (!outerState) return false;
    const states = holes.map(h => inRing(p, h));
    return states.includes(2) || !states.includes(1);
  });
}
export function nearestBoundary(polygons: Footprint, p: XY): XY {
  let best: XY | undefined, distance = Infinity;
  for (const polygon of polygons) for (const ring of polygon) for (let i = 1; i < ring.length; i++) {
    const q = closest(ring[i - 1], ring[i], p), d = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (d < distance) { best = q; distance = d; }
  }
  if (!best) throw new Error('Empty footprint boundary');
  return best;
}
export type Bounds = readonly [number, number, number, number];
export function bounds(polygons: Footprint): Bounds {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const polygon of polygons) for (const ring of polygon) for (const [x, y] of ring) {
    minX = Math.min(minX, x); minY = Math.min(minY, y); maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
  }
  return [minX, minY, maxX, maxY];
}
export function overlaps(b: Bounds, a: XY, c: XY = a): boolean {
  return b[0] <= Math.max(a[0], c[0]) + EPS && b[2] >= Math.min(a[0], c[0]) - EPS &&
    b[1] <= Math.max(a[1], c[1]) + EPS && b[3] >= Math.min(a[1], c[1]) - EPS;
}
/** Intersect a closed vertical prism with an eye→target 3D segment. */
export function blocks(polygons: Footprint, height: number, eye: XY, target: XY, eyeZ: number, targetZ: number): boolean {
  const d = sub(target, eye), length = Math.hypot(...d), cuts = [0, 1];
  const z = (t: number) => eyeZ + (targetZ - eyeZ) * t;
  const zInside = (t: number) => z(t) >= -EPS && z(t) <= height + EPS;
  if (length <= EPS) return covers(polygons, eye) && Math.max(eyeZ, targetZ) >= 0 && Math.min(eyeZ, targetZ) <= height;
  const tEps = EPS / length;
  for (const polygon of polygons) for (const ring of polygon) for (let i = 1; i < ring.length; i++) {
    const a = ring[i - 1], e = sub(ring[i], a), offset = sub(a, eye), denom = cross(d, e);
    if (Math.abs(denom) > 1e-12 * length * Math.max(1, Math.hypot(...e))) {
      const t = cross(offset, e) / denom, u = cross(offset, d) / denom;
      if (t >= -tEps && t <= 1 + tEps && u >= -EPS / Math.max(EPS, Math.hypot(...e)) && u <= 1 + EPS / Math.max(EPS, Math.hypot(...e)))
        cuts.push(Math.max(0, Math.min(1, t)));
    } else if (Math.abs(cross(offset, d)) <= EPS * length) {
      for (const p of [a, ring[i]]) {
        const t = dot(sub(p, eye), d) / dot(d, d);
        if (t >= -tEps && t <= 1 + tEps) cuts.push(Math.max(0, Math.min(1, t)));
      }
    }
  }
  cuts.sort((a, b) => a - b);
  for (let i = 0; i < cuts.length; i++) {
    const t = cuts[i];
    if (zInside(t) && covers(polygons, at(eye, target, t))) return true;
    if (i === 0 || t - cuts[i - 1] <= tEps) continue;
    const prev = cuts[i - 1];
    if (covers(polygons, at(eye, target, (prev + t) / 2)) &&
      Math.min(z(prev), z(t)) <= height + EPS && Math.max(z(prev), z(t)) >= -EPS) return true;
  }
  return false;
}
