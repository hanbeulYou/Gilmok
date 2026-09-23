/** File bridge for actual-data verification. All scoring remains in the shared pure module. */
import { readFileSync, writeFileSync } from 'node:fs';
import { score, reweight } from '../lib/scoring/score.ts';
import { loadPreset } from '../lib/scoring/presets.ts';
import type { Candidate, ScoreContext, ScoreInputs, ScoreReference } from '../lib/scoring/types.ts';
interface Case {
  name: string; primary: ScoreInputs; school: ScoreInputs; reference: ScoreReference;
  candidate: Candidate; context: ScoreContext;
}
const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('Expected input/output paths');
const cases: Case[] = JSON.parse(readFileSync(input, 'utf8'));
const results = cases.map(c => {
  const preset = loadPreset('academy_v0', c.primary.meta.radius_m);
  const result = score(c.primary, c.school, [], null, c.candidate, preset, c.reference, c.context);
  const changed = reweight(result, { ...preset.weights, demand: 50, building: 5 });
  if (JSON.stringify(result.axes.map(a => [a.normalized, a.raw, a.evidence])) !==
      JSON.stringify(changed.axes.map(a => [a.normalized, a.raw, a.evidence])) ||
      JSON.stringify(result.confidence) !== JSON.stringify(changed.confidence))
    throw new Error('Slider invariance failed');
  return { name: c.name, candidate: c.candidate, radius_m: c.primary.meta.radius_m,
    context: c.context, result, slider_invariance: true };
});
writeFileSync(output, JSON.stringify(results, null, 2) + '\n');
