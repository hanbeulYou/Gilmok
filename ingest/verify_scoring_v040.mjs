/** Replay recorded public RPC/Worker inputs; no DB writes or data API calls. */
import { readFileSync, writeFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { URL } from 'node:url';
import process from 'node:process';
import console from 'node:console';
import { score } from '../lib/scoring/score.ts';
import { academyV0 } from '../lib/scoring/presets.ts';

const fixture = readFileSync(new URL('../tests/scoring/fixtures/v040-inputs.json.gz', import.meta.url));
const input = JSON.parse(gunzipSync(fixture).toString());
const results = input.cases.map(c => ({ key: c.key, candidate: c.candidate, before: c.baseline,
  after: score(c.primary, c.school, [], c.exposure, c.candidate, academyV0, c.reference, c.context) }));
const result = { metadata: { ...input.metadata, model_after: academyV0.version,
  fixture_sha256: createHash('sha256').update(fixture).digest('hex') }, results };
const path = new URL('../docs/validation/scoring-v040-20261007.json', import.meta.url);
if (process.argv.includes('--write')) writeFileSync(path, JSON.stringify(result, null, 2) + '\n');
else if (JSON.stringify(JSON.parse(readFileSync(path, 'utf8'))) !== JSON.stringify(result))
  throw new Error('Recorded v0.4.0 results differ; inspect the inputs/model before regenerating');
console.log(JSON.stringify(results.map(r => ({ key: r.key, before: r.before.total, after: r.after.total }))));
