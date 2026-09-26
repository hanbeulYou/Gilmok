/** Compare native browser Worker output with the pure function, then score the Worker result. */
/* global console */
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { URL } from 'node:url';
import { deepStrictEqual } from 'node:assert';

const require = createRequire(import.meta.url);
const { computeVisibility } = require('../.local/scoring-build/lib/visibility/compute.js');
const { score } = require('../.local/scoring-build/lib/scoring/score.js');
const { loadPreset } = require('../.local/scoring-build/lib/scoring/presets.js');
const directory = fileURLToPath(new URL('../.local/validation/s2-4-20260926/', import.meta.url));
const input = JSON.parse(readFileSync(directory + 'inputs.json', 'utf8'));
const browser = JSON.parse(readFileSync(directory + 'browser.json', 'utf8'));
const results = input.cases.map(c => {
  const run = browser.runs.find(r => r.key === c.key);
  deepStrictEqual(run.result, computeVisibility(c.scene));
  const result = score(c.primary, c.school, c.scene.buildings, run.result, c.candidate,
    loadPreset('academy_v0', 800), input.reference, c.context);
  const endpoints = result.axes.filter(a => a.normalized === 0 || a.normalized === 100).map(a => a.key);
  return { key: c.key, candidate: c.candidate, address_resolution: c.address_resolution,
    result, exposure: { status: run.result.status, visible_ratio: run.result.visible_ratio ?? null,
      summary: run.result.summary, building_count: c.scene.buildings.length,
      coverage: c.scene.coverage, reason: run.result.reason ?? null },
    worker: { compute_ms: run.computeMs, roundtrip_ms: run.roundtripMs, pure_equal: true },
    anomalies: { total_null: result.total === null, confidence_below_30: result.confidence.value < 30,
      endpoint_axes: endpoints, endpoint_count: endpoints.length,
      nonnull_axis_count: result.axes.filter(a => a.normalized !== null).length } };
});
const candidates = results.slice(0, 3);
const ranges = candidates[0].result.axes.map(axis => {
  const values = candidates.map(c => c.result.axes.find(a => a.key === axis.key).normalized);
  return { key: axis.key, values,
    range: values.every(v => v !== null) ? Math.max(...values) - Math.min(...values) : null };
});
const order = [...candidates].sort((a, b) => b.result.total - a.result.total).map(c => c.key);
const output = { metadata: { ...input.metadata, worker_user_agent: browser.userAgent },
  actual_order: order, ranges, results };
writeFileSync(directory + 'results.json', JSON.stringify(output, null, 2) + '\n');
console.log(JSON.stringify({ order, ranges, results: results.map(c => ({ key: c.key,
  total: c.result.total, confidence: c.result.confidence, axes: c.result.axes.map(a => ({ key: a.key,
    score: a.normalized, missing_reason: a.missing_reason })), anomalies: c.anomalies })) }));
