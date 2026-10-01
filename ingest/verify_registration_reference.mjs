/** Local replay against recorded S2 inputs; no external data API calls. */
/* global console */
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { Buffer } from 'node:buffer';
import { deepStrictEqual, ok } from 'node:assert';
import process from 'node:process';

const require = createRequire(import.meta.url);
const { extractReferenceRaw } = require('../.local/scoring-build/lib/scoring/raw.js');
const { loadPreset } = require('../.local/scoring-build/lib/scoring/presets.js');
const { score } = require('../.local/scoring-build/lib/scoring/score.js');
const { computeVisibility } = require('../.local/scoring-build/lib/visibility/compute.js');
const [mode, inputPath, outputPath, rpcPath] = process.argv.slice(2);
if (!['raw', 'verify'].includes(mode) || !inputPath || !outputPath) throw new Error('Expected raw/verify inputs output [rpc]');
const input = JSON.parse(readFileSync(inputPath, 'utf8'));
const preset = loadPreset('academy_v0', 800);
if (mode === 'raw') {
  const requests = input.cases.map(c => ({ key: c.key, candidate: c.candidate,
    pnu: c.address_resolution?.pnu ?? null,
    raw: Object.fromEntries(Object.entries(extractReferenceRaw(c.primary, c.school, c.context, preset))
      .filter(([key]) => key !== 'cluster').map(([key, value]) => [key, value.value])),
  }));
  writeFileSync(outputPath, JSON.stringify(requests));
} else {
  const rpc = JSON.parse(readFileSync(rpcPath, 'utf8'));
  const results = input.cases.map(c => {
    const actual = rpc.find(row => row.key === c.key);
    deepStrictEqual(actual.context.lat, c.candidate.lat);
    deepStrictEqual(actual.context.lng, c.candidate.lng);
    if (c.address_resolution) {
      deepStrictEqual(actual.context.status, 'matched');
      deepStrictEqual(actual.context.building.id, c.address_resolution.building_id);
    }
    const exposure = computeVisibility(c.scene);
    const expected = score(c.primary, c.school, c.scene.buildings, exposure, c.candidate,
      preset, input.reference, c.context);
    const result = score(c.primary, c.school, c.scene.buildings, exposure, c.candidate,
      preset, actual.reference, actual.context.context);
    deepStrictEqual(result, expected);
    ok(!('distributions' in actual.reference));
    return { key: c.key, total: result.total, confidence: result.confidence.value,
      axes: result.axes.map(a => ({ key: a.key, normalized: a.normalized })),
      context_sql_ms: actual.context_sql_ms, percentile_sql_ms: actual.percentile_sql_ms,
      response_bytes: Buffer.byteLength(JSON.stringify(actual.reference)), full_score_equal: true };
  });
  const summary = { scope: 'local S2 frozen-input replay; direct SQL, not HTTP/browser', results };
  writeFileSync(outputPath, JSON.stringify(summary, null, 2) + '\n');
  console.log(JSON.stringify({ cases: results.length, full_score_equal: true,
    totals: results.slice(0, 3).map(r => r.total) }));
}
