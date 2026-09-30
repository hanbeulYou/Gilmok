/** Frozen v0.3 T0/T1 eight-axis comparison; never recalibrate or publish data. */
/* global console */
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { deepStrictEqual } from 'node:assert';
import process from 'node:process';
const require = createRequire(import.meta.url);
const { computeVisibility } = require('../.local/scoring-build/lib/visibility/compute.js');
const { score } = require('../.local/scoring-build/lib/scoring/score.js');
const { loadPreset } = require('../.local/scoring-build/lib/scoring/presets.js');
const baselineOnly = process.argv.includes('--baseline-only');
const directory = process.argv.slice(2).find(arg => !arg.startsWith('--'))
  ?? '.local/validation/s3-2-a0-juso';
const read = path => JSON.parse(readFileSync(path, 'utf8'));
const baseline = read('.local/validation/s2-4-v03-20260926/inputs.json');
const current = baselineOnly ? { ...baseline, cases: baseline.cases.slice(0, 3) }
  : read(`${directory}/inputs.json`);
const expected = read('docs/validation/s2-4-v03-20260926.json');
const preset = loadPreset('academy_v0', 800);
deepStrictEqual(preset.version, '0.3');
function calculate(c, reference) {
  const exposure = computeVisibility(c.scene);
  return score(c.primary, c.school, c.scene.buildings, exposure,
    c.candidate, preset, reference, c.context);
}
const results = current.cases.map(c => {
  const old = baseline.cases.find(row => row.key === c.key);
  const t0 = calculate(old, baseline.reference);
  deepStrictEqual(t0, expected.results.find(row => row.key === c.key).result);
  const t1 = calculate(c, current.reference);
  return { key: c.key, candidate: c.candidate, t0, t1,
    axes: t1.axes.map(axis => {
      const before = t0.axes.find(row => row.key === axis.key).normalized;
      return { key: axis.key, before, after: axis.normalized,
        delta: before === null || axis.normalized === null ? null : axis.normalized - before };
    }),
    total_delta: t1.total === null || t0.total === null ? null : t1.total - t0.total };
});
const output = { stage: baselineOnly ? 'T0-replay' : 'T1', preset_version: '0.3',
  baseline_reproduced: true,
  background_replaced: false, results,
  order: [...results].sort((a, b) => (b.t1.total ?? -1) - (a.t1.total ?? -1)).map(c => c.key) };
if (!baselineOnly) {
  writeFileSync(`${directory}/scores.json`, JSON.stringify(output, null, 2) + '\n');
}
console.log(JSON.stringify(output, null, 2));
